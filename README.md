# An Android app in C under 2 KB

A complete Android app written in C, without Java, Gradle or the C library. It fills the screen with a gradient. The ARM64 APK is **1,768 bytes** with a standard self-signed certificate, and **1,600 bytes** with an experimental one. All builds run on an Android 16 phone; see [Testing and limitations](#testing-and-limitations) for details.

<img src="screenshot.png" width="200" alt="The app: a gradient from blue to pink at the top, green to yellow at the bottom">

*The earlier build on an Android 16 phone.*

The first article, [An Android app in C under 2 KB](https://regisvidal.com/articles/tiny-android-app-in-c/), explains the original 1,854-byte build.

**Update, 17 November 2026:** a second article, [Making the tiny Android app smaller](https://regisvidal.com/articles/tiny-android-app-in-c-again/), explains how the build went from 1,854 to 1,768 bytes, and the certificate profiles that reach 1,600.

| File | What it is |
|---|---|
| `main.c` | The app: window callbacks, gradient and input handling |
| `native_window.h` | Platform window layout, named operations and inline NDK replacements |
| `AndroidManifest.xml` | Name, SDK versions and launcher entry |
| `Makefile` | Compiles, packages and signs |
| `apk.py` | Shrinks ELF headers and binary XML, prepares small certificates, signs without padding |

## Build

You need the Android SDK with the NDK, build-tools and one platform, plus `zip`, `advzip` (Debian package `advancecomp`), OpenSSL 3.4 or later, Python 3 and Java.

```sh
make                # app.apk, signed by the SDK's apksigner
make tiny           # tiny.apk, original certificate, no signing-block padding
make tiny-short     # tiny-short.apk, shortened P-256 certificate
make record         # record.apk, compressed P-256 certificate public point
make record-p224    # record-p224.apk, separate P-224 signing key
make install        # installs tiny.apk only
make release        # tiny APKs for arm64-v8a and armeabi-v7a
```

Run `make clean` before changing ABI:

```sh
make clean
make ABI=armeabi-v7a record
```

The SDK is `$ANDROID_HOME`, else `/opt/android-sdk`. The Makefile takes the last NDK, build-tools and platform folder in alphabetical order. `make SDK=... NDK=... BT=... JAR=...` selects others. The x86_64 target remains untested.

## Sizes

Measured with NDK r28, clang 19, build-tools 35, platform 36 and advzip zopfli with 1,000 iterations.

| Target | ARM64 (bytes) | ARM32 (bytes) | Desktop verification |
|---|---:|---:|---|
| `tiny` | 1,768 | 1,721 | Passes |
| `tiny-short` | 1,677 | 1,632 | Passes |
| `record` | 1,626 | 1,580 | Certificate rejected |
| `record-p224` | 1,600 | 1,555 | Certificate rejected |

Sizes depend slightly on the key and the DER encoding of the ECDSA signature. These measurements use fixed local keys. Freshly generated keys can give different sizes.

## Signing files

The first build creates `key.pem` and `cert.der`. Keep both: `make` and `make tiny` continue to use that identity.

The smaller profiles write separate certificates: `cert-short.der`, `cert-record.der` and `cert-record-p224.der`. The P-224 target also creates `record-key.pem`. `make clean` retains these files. Private keys are ignored by git.

All profiles sign the APK with ECDSA and SHA-256. The shortened certificate has an empty self-signature and shortened metadata. The record profiles also have empty issuer/subject names and a compressed EC public point. The signature record keeps its copy of the public key uncompressed, as required by the tested Android parser.

Changing the certificate changes the signing identity, even if the public key stays the same. An experimental APK cannot update an installation signed with the original certificate. P-224 also reduces key strength and is not among the curves listed in the [APK v2 specification](https://source.android.com/docs/security/features/apksigning/v2). Its acceptance here is an observation on Android 12 and Android 16.

`apk.py cert short|record SOURCE_CERT KEY OUT_CERT` accepts this project's X.509 v1 certificate layout. It preserves the source serial and validity dates. It is not a general certificate editor.

## How it works

1. Android's built-in `NativeActivity` loads `lib/<abi>/libmain.so`. The manifest sets `android:hasCode="false"`.
2. Inline wrappers in `native_window.h` call the platform window's `perform` function pointer. The four remaining imports from `libandroid.so` handle input and the looper.
3. ARM64 draws the gradient with integer division, in a loop that counts down, and takes its callback addresses with one `adr` instruction each. ARM32 keeps a subtraction loop, avoiding a compiler runtime helper.
4. `apk.py` overlaps ELF headers and binary-XML string storage, removes unused metadata, and normalizes manifest values. On ARM64 the library has a System V hash table, which `apk.py hash` cuts to one bucket that points to the export. ARM32 keeps the GNU table: with a System V table, the export would lie under a section header.
5. advzip compresses the two files. The signer writes a v2 signing block without apksigner's alignment padding.

## Testing and limitations

- The eight APKs listed above, both ABIs, were installed unchanged on a physical Android 16 phone. Each passed launch (ARM32 after Android's 32-bit warning), Home and resume, force-stop and restart, and Back and relaunch. After each one: two taps, a 12-second wait, and a screenshot identical to the original gradient outside the system bars.
- The previous builds, without the `adr` instructions and the hash table changes and 1 to 31 bytes larger, were tested on a physical Android 12 phone. Those tests used separately named copies to preserve the existing app. The current builds have not been run on Android 12.
- The checks do not cover rotation, long sessions, other Android versions or 16 KB page devices.
- `aapt2 dump badging` matches the original label, launcher and SDK values. Desktop signature verification passes only for `tiny` and `tiny-short`; the record targets do not claim a verifier pass.
- Direct window dispatch depends on platform structure layout and operation numbers outside the public NDK contract.
- The manifest and ELF use layouts that some other tools reject. `--no-rosegment` and `-z norelro` also weaken memory protections.
- This project is for sideloading and learning. No Play distribution is claimed.

## License

MIT License, in `LICENSE`.
