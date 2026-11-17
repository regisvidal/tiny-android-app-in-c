/* Copyright (c) 2026 Regis Vidal. MIT License, see LICENSE. */
#ifndef TINY_NATIVE_WINDOW_H
#define TINY_NATIVE_WINDOW_H

#include <android/native_window.h>
#include <stddef.h>
#include <stdint.h>

/* Android 12 platform definitions, not part of the public NDK interface:
 * https://android.googlesource.com/platform/frameworks/native/+/android-12.0.0_r1/libs/nativewindow/include/system/window.h
 * https://android.googlesource.com/platform/frameworks/native/+/android-12.0.0_r1/libs/nativewindow/include/apex/window.h
 * Only the prefix through perform is declared. Android owns the object. */
/* Platform layout from Android's nativebase.h and system/window.h.
 * The public NDK leaves ANativeWindow opaque. Keep the prefix through
 * perform: offset 152 on 64-bit targets, 88 on 32-bit targets. */
struct android_native_base_t {
    int magic, version;
    void *reserved[4];
    void (*incRef)(struct android_native_base_t *);
    void (*decRef)(struct android_native_base_t *);
};

struct ANativeWindow {
    struct android_native_base_t common;
    const uint32_t flags;
    const int minSwapInterval, maxSwapInterval;
    const float xdpi, ydpi;
    intptr_t oem[4];
    int (*setSwapInterval)(struct ANativeWindow *, int);
    int (*dequeueBuffer_DEPRECATED)(struct ANativeWindow *, void **);
    int (*lockBuffer_DEPRECATED)(struct ANativeWindow *, void *);
    int (*queueBuffer_DEPRECATED)(struct ANativeWindow *, void *);
    int (*query)(const struct ANativeWindow *, int, int *);
    int (*perform)(struct ANativeWindow *, int, ...);
};

_Static_assert(offsetof(struct ANativeWindow, perform) ==
               (sizeof(void *) == 8 ? 152 : 88), "window perform offset");

/* Operations dispatched by ANativeWindow.perform. */
enum {
    NATIVE_WINDOW_SET_BUFFERS_FORMAT = 9,          /* pixel format */
    NATIVE_WINDOW_SET_SCALING_MODE = 10,           /* buffer-to-window scaling */
    NATIVE_WINDOW_LOCK = 11,                      /* acquire writable pixels */
    NATIVE_WINDOW_UNLOCK_AND_POST = 12,           /* submit the drawn buffer */
    NATIVE_WINDOW_SET_BUFFERS_USER_DIMENSIONS = 15 /* requested width, height */
};

enum {
    /* Wait for a buffer matching the window size before updating it. */
    NATIVE_WINDOW_SCALING_MODE_FREEZE = 0,
    /* Scale both dimensions of the buffer to the window size. */
    NATIVE_WINDOW_SCALING_MODE_SCALE_TO_WINDOW = 1
};

/* Inline equivalents of the NDK wrappers in ANativeWindow.cpp:
 * https://android.googlesource.com/platform/frameworks/native/+/android-12.0.0_r1/libs/nativewindow/ANativeWindow.cpp
 *
 * width=height=0 restores the window's default buffer dimensions. When
 * both dimensions are nonzero, buffers are scaled to the window. Each
 * operation's error is returned without attempting the following ones. */
static inline int32_t tiny_window_set_buffers_geometry(
        ANativeWindow *window, int32_t width, int32_t height, int32_t format) {
    int32_t err = window->perform(window, NATIVE_WINDOW_SET_BUFFERS_FORMAT, format);
    if (err) {
        return err;
    }
    err = window->perform(window, NATIVE_WINDOW_SET_BUFFERS_USER_DIMENSIONS,
                          width, height);
    if (err) {
        return err;
    }
    int mode = width && height ? NATIVE_WINDOW_SCALING_MODE_SCALE_TO_WINDOW
                              : NATIVE_WINDOW_SCALING_MODE_FREEZE;
    return window->perform(window, NATIVE_WINDOW_SET_SCALING_MODE, mode);
}

static inline int32_t tiny_window_lock(
        ANativeWindow *window, ANativeWindow_Buffer *buffer, ARect *dirty_bounds) {
    return window->perform(window, NATIVE_WINDOW_LOCK, buffer, dirty_bounds);
}

static inline int32_t tiny_window_unlock_and_post(ANativeWindow *window) {
    return window->perform(window, NATIVE_WINDOW_UNLOCK_AND_POST);
}

#endif
