# An Android app in C under 2 KB

A complete Android app under **2 KB** (1,854 bytes), written in C, without Java, Gradle or the C library. It fills the screen with a gradient.

<img src="screenshot.png" width="200" alt="The app: a gradient from blue to pink at the top, green to yellow at the bottom">

*The app on an Android 16 phone.*

The article [An Android app in C under 2 KB](https://regisvidal.com/articles/tiny-android-app-in-c/) explains in detail how to squeeze every byte out of an APK.

| File                  | What it is                                                                     |
|-----------------------|--------------------------------------------------------------------------------|
| `main.c`              | The whole app (~65 lines)                                                      |
| `AndroidManifest.xml` | Describes the app to Android: name, SDK versions, launcher entry               |
| `Makefile`            | Compiles, packages and signs, with the SDK tools, zip, advzip and openssl      |
| `apk.py`              | Shrinks the ELF headers and the binary manifest, signs the APK without padding |

## Build

You need the Android SDK with the NDK, build-tools and one platform, plus `zip`, `advzip` (Debian package `advancecomp`), `openssl` 3.4 or later, `python3` and Java (for apksigner).

```sh
make              # app.apk:  signed by the SDK's apksigner  (8,349 bytes)
make tiny         # tiny.apk: same app, signed by apk.py     (1,854 bytes)
make install      # adb install tiny.apk
make release      # arm64-v8a and armeabi-v7a APKs
make ABI=armeabi-v7a tiny   # other ABIs: armeabi-v7a, x86_64 (make clean first)
```

The SDK is `$ANDROID_HOME`, else `/opt/android-sdk`. In it, the Makefile takes the last NDK, build-tools and platform folder in alphabetical order, usually the newest. `make SDK=... NDK=... BT=... JAR=...` picks others.

The first build creates your signing key, `key.pem`, and its certificate, `cert.der`. Keep them: Android only installs an updated app signed with the same certificate.

## How it works

1. No Java: `android:hasCode="false"`, and Android's built-in `NativeActivity` loads `lib/<abi>/libmain.so`.
2. `main.c` draws the gradient into the window's pixel buffer and answers every input event.
3. The library is compiled and linked for size, without the C library: its only imports are 7 functions of `libandroid.so`. `apk.py elf` and `apk.py phdr` then shrink its ELF headers.
4. `aapt2` compiles the manifest without SDK metadata or namespaces, `apk.py manifest` shrinks it further, and the Makefile removes `resources.arsc`.
5. `advzip` deflates the files again with the zopfli algorithm, for better compression.
6. `apk.py sign` writes the same v2 signature as `apksigner`, without the 4 KB alignment that makes the APK four times bigger.

## Testing and limitations

- Both APKs pass `apksigner verify` and `aapt2 dump badging`.
- Tested on an Android 12 and 16 phone. Not tested: 16 KB page devices and x86_64.
- The binary manifest is not well-formed XML, since the closing tags at the end are gone, but Android reads it.
- `--no-rosegment` and `-z norelro` weaken the library's protection against memory bugs.
- The library breaks the ELF spec, and `nm` and `objdump` no longer read it.
- Play wants App Bundles for new apps: this project is for sideloading and learning.

## License

MIT License, in `LICENSE`.
