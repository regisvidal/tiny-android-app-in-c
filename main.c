/* Copyright (c) 2026 Regis Vidal. MIT License, see LICENSE. */
/* The whole app. NativeActivity loads lib/<abi>/libmain.so and calls
 * ANativeActivity_onCreate(), which registers callbacks. No Java, no C
 * library: only libandroid.so. */
#include <android/native_activity.h>

/* Gradient: red grows left to right, green top to bottom. x * 255 / w
 * without a divide, which some armv7 cores lack: add 255 per pixel, and
 * each time the sum reaches w, take w off and add 1. */
static void draw(ANativeActivity *activity, ANativeWindow *window) {
    ANativeWindow_Buffer b;

    (void)activity;
    ANativeWindow_setBuffersGeometry(window, 0, 0, WINDOW_FORMAT_RGBX_8888);
    if (ANativeWindow_lock(window, &b, 0) != 0) {
        return;
    }

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

    ANativeWindow_unlockAndPost(window);
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
    AInputQueue_attachLooper(q, ALooper_forThread(), 0, on_input, q);
}

/* No onInputQueueDestroyed: Android detaches the queue itself. */

void ANativeActivity_onCreate(ANativeActivity *a, void *state, size_t size) {
    (void)state;
    (void)size;
    a->callbacks->onNativeWindowRedrawNeeded = draw;
    a->callbacks->onInputQueueCreated = input_created;
}
