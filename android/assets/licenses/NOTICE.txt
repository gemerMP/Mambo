# Third-party components

| Component | Version | License | Exact upstream source |
|---|---|---|---|
| AndroidLibXrayLite | v26.10.10 | LGPL-3.0 | https://github.com/2dust/AndroidLibXrayLite/tree/v26.10.10 |
| Xray-core | v26.10.10 | MPL-2.0 | https://github.com/XTLS/Xray-core/tree/v26.10.10 |
| hev-socks5-tunnel | 2.18.0 | MIT | https://github.com/heiher/hev-socks5-tunnel/tree/2.18.0 |

License texts are in `licenses/` and inside the APK. Corresponding top-level
source archives are included in `upstream/`; upstream `go.mod`, `go.sum`, and
`.gitmodules` identify transitive dependencies and source locations.
The AARs used by build.py are unmodified upstream release artifacts.

Android SDK / Build Tools and Eclipse ECJ are build-time tools, downloaded
from Google and Maven Central with pinned SHA-256 hashes. They are not shipped
as app runtime components. SDK notices remain in the downloaded SDK.

The build script compiles all Mambo Java sources and combines them with the
replaceable AAR classes and native shared objects. You can replace either AAR,
update its checksum in build.py, rebuild and sign with your own key. The private
original signing key is deliberately delivered separately from the public
source archive. No anti-tamper checks or restrictions on debugging modified
library versions are included.

Artwork and audio: supplied in this conversation for this project; original
rights remain with their respective holders. Red character artwork is the
previously generated project asset. These assets are not relicensed as MIT.
