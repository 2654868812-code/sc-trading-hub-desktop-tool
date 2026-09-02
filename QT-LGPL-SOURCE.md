# Qt / PySide6 LGPL Source and Replacement Instructions

FT-DataUpload 2.0.0 distributes the unmodified PySide6 Essentials, Shiboken6,
and Qt 6.11.2 shared libraries under GNU LGPL version 3. Their license terms
are included in `COPYING.LESSER` and `COPYING`.

The Fantian Trading Hub Desktop Assistant application itself is proprietary
software. The LGPL terms described here apply to the separately distributed
Qt, PySide6, and Shiboken6 libraries, not to the application code.

Recipients can download the complete, distributor-controlled source archives
for the distributed version from the authenticated desktop release page:

- PySide6 and Shiboken6 6.11.2:
  https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.2-src/pyside-setup-everywhere-src-6.11.2.tar.xz
- Qt 6.11.2:
  https://download.qt.io/archive/qt/6.11/6.11.2/single/qt-everywhere-src-6.11.2.zip

No local modifications are made to those libraries. Keep a copy of both exact
source archives with every published binary release rather than relying only
on the continued availability of the upstream links. If the distributed
libraries are patched later, publish the corresponding modified source and
build scripts alongside that release.

For at least three years after the last distribution of this release, anyone
who receives its object code may request a copy of those exact library sources
through the support contact published on the FT Trading Hub website. The charge,
if any, will not exceed the reasonable
cost of physically providing the source. This offer applies even if an
upstream URL later becomes unavailable.

The upstream URLs above identify provenance only and are not the compliance
download mechanism. The release operator retains and serves both archives
listed in `UPSTREAM-SOURCES.json`.
That manifest pins their official URLs, byte sizes, and SHA-256 hashes; the
release runbook downloads and verifies them before publishing version 2.0.0.

## Replacing the libraries

This is an ordinary Windows directory distribution, not a statically linked or
single-file executable. Exit FT-DataUpload, make a backup of its `_internal`
directory, and replace the PySide6, Shiboken6, and Qt DLL/PYD files there with
ABI-compatible files built from the corresponding source. Preserve the file
names and relative paths, then start `FT-DataUpload.exe` normally. The program
does not verify or cryptographically restrict replacement library files.

Modified libraries must remain compatible with the Python version and x86-64
Windows ABI used by the release. A failure to start after replacement usually
means the replacement set is incomplete or ABI-incompatible; restore the
backup and replace the complete matching set.

No application license term prohibits reverse engineering when it is needed
to debug a modification to an LGPL-covered library.
