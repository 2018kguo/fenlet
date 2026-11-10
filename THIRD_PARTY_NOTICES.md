# Third-party notices

Fenlet's source is MIT licensed. Its prebuilt app also contains an unmodified
CPython runtime from [Astral's python-build-standalone](https://github.com/astral-sh/python-build-standalone),
installed through [uv](https://github.com/astral-sh/uv).

CPython retains its Python Software Foundation license at
`Contents/Resources/runtime/lib/python3.14/LICENSE.txt` in the app. License
texts for its upstream dependencies, including OpenSSL, are retained under
`Contents/Resources/python-licenses`. Their source URLs and hashes are in
[the manifest](vendor/python-licenses/manifest.json). That directory includes
optional upstream components; their inclusion is not a claim that every
component is linked into this build. Fenlet does not modify CPython.

No Python packages are required by Fenlet. The runtime's existing package
metadata and notices remain intact. Apple system frameworks and system app
icons are supplied by macOS and are not redistributed as Fenlet assets.

The app embeds [Sparkle 2.10.1](https://github.com/sparkle-project/Sparkle/releases/tag/2.10.1)
for signed updates. Its MIT license and dependency notices are included at
`Contents/Resources/Sparkle-LICENSE.txt`. The source archive is pinned to
SHA-256 `1a856d2a9edb8e628de88121d7be04cf0e2167f8641650b78fca00b14244cf27`.

The README demo uses synthetic window content. It contains no user desktop
captures, private documents, credentials, or real conversations.
