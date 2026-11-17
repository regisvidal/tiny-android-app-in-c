# Copyright (c) 2026 Regis Vidal. MIT License, see LICENSE.
# An Android app in C under 2 KB.
#   make          -> app.apk   signed by the SDK's apksigner
#   make tiny     -> tiny.apk  same APK, signed by apk.py (no 4 KB padding)
#   make tiny-short  -> tiny-short.apk, shortened P-256 certificate
#   make record      -> record.apk, compressed P-256 certificate public key
#   make record-p224 -> record-p224.apk, separate experimental P-224 key
#   make install  -> adb install tiny.apk
#   make release  -> tiny-android-app-in-c-<abi>.apk, arm64-v8a and armeabi-v7a
#   make ABI=armeabi-v7a, or x86_64 (untested). Run `make clean` first.

ABI ?= arm64-v8a
SDK ?= $(or $(ANDROID_HOME),/opt/android-sdk)
NDK ?= $(lastword $(wildcard $(SDK)/ndk/*))
BT  ?= $(lastword $(wildcard $(SDK)/build-tools/*))
JAR ?= $(lastword $(wildcard $(SDK)/platforms/android-*/android.jar))

TRIPLE_arm64-v8a   = aarch64-linux-android
TRIPLE_armeabi-v7a = armv7a-linux-androideabi
TRIPLE_x86_64      = x86_64-linux-android
# armv7: Thumb code, no .ARM.exidx entries (internal clang option)
THUMB_armeabi-v7a  = -mthumb -Xclang -exception-model=dwarf
# arm64: SysV hash table, cut to one bucket by apk.py hash. armv7 keeps
# GNU: with SysV the export is symbol 1, under a section header.
HASH_arm64-v8a     = -Wl,--hash-style=sysv
TB = $(NDK)/toolchains/llvm/prebuilt/linux-x86_64/bin
CC = $(TB)/clang --target=$(TRIPLE_$(ABI))24

# Size flags: README.md and the article explain each one.
CFLAGS  = -Oz -fPIC -ffunction-sections -fdata-sections \
          -fno-asynchronous-unwind-tables -fno-unwind-tables \
          -fomit-frame-pointer -fno-plt $(THUMB_$(ABI)) \
          -Wall -Wextra
LDFLAGS = -shared -nostdlib -s -Wl,--gc-sections \
          -Wl,--no-rosegment,-z,norelro \
          -Wl,-z,lazy,-z,nognustack \
          -Wl,--pack-dyn-relocs=android \
          -Wl,-z,max-page-size=16384 $(HASH_$(ABI))
LIBS    = -landroid

LIB = lib/$(ABI)/libmain.so

app.apk: unsigned.apk key.pk8 cert.der
	$(BT)/apksigner sign --key key.pk8 --cert cert.der --min-sdk-version 24 \
	  --v1-signing-enabled false --v3-signing-enabled false --v4-signing-enabled false \
	  --out $@ unsigned.apk
	@ls -l $@

tiny: tiny.apk
tiny.apk: unsigned.apk key.pem cert.der apk.py
	python3 apk.py sign unsigned.apk key.pem cert.der $@
	$(BT)/apksigner verify $@
	@ls -l $@

# Short names pass the desktop verifier. Both record profiles are only
# accepted by the tested Android 12 and 16 phones; apksigner rejects their
# certificates.
tiny-short: tiny-short.apk
tiny-short.apk: unsigned.apk key.pem cert-short.der apk.py
	python3 apk.py sign unsigned.apk key.pem cert-short.der $@
	$(BT)/apksigner verify $@
	@ls -l $@

record: record.apk
record.apk: unsigned.apk key.pem cert-record.der apk.py
	python3 apk.py sign unsigned.apk key.pem cert-record.der $@
	@ls -l $@

record-p224: record-p224.apk
record-p224.apk: unsigned.apk record-key.pem cert-record-p224.der apk.py
	python3 apk.py sign unsigned.apk record-key.pem cert-record-p224.der $@
	@ls -l $@

cert-short.der: cert.der key.pem apk.py
	python3 apk.py cert short cert.der key.pem $@

cert-record.der: cert.der key.pem apk.py
	python3 apk.py cert record cert.der key.pem $@

cert-record-p224.der: cert.der record-key.pem apk.py
	python3 apk.py cert record cert.der record-key.pem $@

# Separate identity: never replace key.pem to try the smaller curve.
record-key.pem:
	openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:secp224r1 -out $@

$(LIB): main.c native_window.h apk.py
	mkdir -p $(@D)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $< $(LIBS)
	python3 apk.py elf $@
	python3 apk.py phdr $@
	python3 apk.py hash $@

# Binary manifest without resources.arsc, library added with a fixed
# date and mode, then both entries deflated again with zopfli.
unsigned.apk: AndroidManifest.xml $(LIB) apk.py
	$(BT)/aapt2 link -o $@ -I $(JAR) \
	  --manifest AndroidManifest.xml \
	  --no-compile-sdk-metadata --no-xml-namespaces
	zip -q -d $@ resources.arsc
	python3 apk.py manifest $@
	touch -t 198001010000 $(LIB)
	chmod 755 $(LIB)
	zip -q -9 -X -D $@ $(LIB)
	advzip -q -z -4 -i 1000 $@

# P-256 is the smallest EC curve listed by the APK v2 specification.
key.pem:
	openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out $@
# X.509 v1, ends on 31 December 2049 (OpenSSL 3.4), retried until it
# is 256 bytes.
cert.der: key.pem
	until [ -s $@ ] && [ $$(stat -c%s $@) -le 256 ]; do \
	  printf '[req]\ndistinguished_name=dn\n[dn]\n' | \
	  openssl req -new -x509 -x509v1 -key key.pem -subj /CN=a \
	    -not_after 20491231235959Z -set_serial 1 -config /dev/stdin \
	    -outform DER -out $@ || exit 1; done
key.pk8: key.pem
	openssl pkcs8 -topk8 -nocrypt -in key.pem -outform DER -out $@

install: tiny.apk
	adb install -r tiny.apk

# Both ABIs, the default ABI last.
release:
	for a in armeabi-v7a arm64-v8a; do \
	  rm -rf lib unsigned.apk tiny.apk && \
	  $(MAKE) ABI=$$a tiny && cp tiny.apk tiny-android-app-in-c-$$a.apk || exit 1; \
	done

clean:
	rm -rf lib unsigned.apk app.apk tiny.apk tiny-short.apk record.apk record-p224.apk tiny-android-app-in-c-*.apk

.PHONY: tiny tiny-short record record-p224 install release clean
