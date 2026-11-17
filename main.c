/* Copyright (c) 2026 Regis Vidal. MIT License, see LICENSE. */
/* The whole app. NativeActivity loads lib/<abi>/libmain.so and calls
 * ANativeActivity_onCreate(), which registers callbacks. No Java, no C
 * library: only libandroid.so. */
#include <android/native_activity.h>
#include "native_window.h"

/* Gradient: red grows left to right, green top to bottom. ARM64 has
 * integer division. Other targets keep the subtraction loop, since some
 * armv7 cores have no divide instruction. Rows advance by the stride. */
static void draw(ANativeActivity *activity, ANativeWindow *window) {
    ANativeWindow_Buffer b;

    (void)activity;
    tiny_window_set_buffers_geometry(window, 0, 0, WINDOW_FORMAT_RGBX_8888);
    if (tiny_window_lock(window, &b, 0) != 0) {
        return;
    }

#if defined(__aarch64__)
    unsigned *row = b.bits;
    unsigned w = b.width, h = b.height;
    if (w && h) {
        /* Unsigned accumulators keep x * 255 and y * 255 modulo 2^32. */
        unsigned y = 0, gy = 0;
        do {
            unsigned c = 0xff800000u | ((gy / h) << 8);
            unsigned rx = 0, count = w;
            unsigned *pixel = row;
            do {
                *pixel++ = c | (rx / w);
                rx += 255;
            } while (--count);
            gy += 255;
            row += b.stride;
        } while (++y < h);
    }
#else
    unsigned *row = b.bits, g = 0;
    unsigned w = b.width, h = b.height, gy = 0;
    for (unsigned y = 0; y < h; y++, row += b.stride) {
        unsigned c = 0xff800000u | g << 8; /* X=ff B=80 G R */
        unsigned rx = 0;
        for (unsigned x = 0; x < w; x++) {
            row[x] = c;
            for (rx += 255; rx >= w; rx -= w) {
                c++;
            }
        }
        for (gy += 255; gy >= h; gy -= h) {
            g++;
        }
    }

#endif

    tiny_window_unlock_and_post(window);
}

/* Answer every event with "not handled": Back still closes the app, and
 * Android does not report the app as not responding. */
static int on_input(int fd, int events, void *data) {
    AInputQueue *q = data;
    AInputEvent *e;

    (void)fd;
    (void)events;
    while (AInputQueue_getEvent(q, &e) >= 0) {
        /* No preDispatchEvent(): it only answers "not handled" too. */
        AInputQueue_finishEvent(q, e, 0);
    }
    return 1; /* keep listening */
}

/* The main thread's looper calls on_input when the queue has events. */
static void input_created(ANativeActivity *a, AInputQueue *q) {
    (void)a;
#if defined(__aarch64__)
    ALooper *looper = ALooper_forThread();
    ALooper_callbackFunc callback;
    /* ADR reaches this local callback within +/-1 MiB; the linker checks
     * the range. Keep it after the looper call so no extra saved register
     * is needed to carry the callback address across that call. */
    __asm__ volatile("adr %0, %c1" : "=r"(callback) : "S"(on_input));
#else
    ALooper *looper = ALooper_forThread();
    ALooper_callbackFunc callback = on_input;
#endif
    AInputQueue_attachLooper(q, looper, 0, callback, q);
}

/* No onInputQueueDestroyed: Android detaches the queue itself. */

void ANativeActivity_onCreate(ANativeActivity *a, void *state, size_t size) {
    (void)state;
    (void)size;
#if defined(__aarch64__)
    __typeof__(a->callbacks->onNativeWindowRedrawNeeded) redraw;
    __typeof__(a->callbacks->onInputQueueCreated) input;
    /* Local PC-relative addresses use one ADR instead of NOP + ADR from
     * the linker-relaxed ADRP + ADD pair. The same +/-1 MiB limit applies. */
    __asm__("adr %0, %c1" : "=r"(redraw) : "S"(draw));
    __asm__("adr %0, %c1" : "=r"(input) : "S"(input_created));
    a->callbacks->onNativeWindowRedrawNeeded = redraw;
    a->callbacks->onInputQueueCreated = input;
#else
    a->callbacks->onNativeWindowRedrawNeeded = draw;
    a->callbacks->onInputQueueCreated = input_created;
#endif
}
