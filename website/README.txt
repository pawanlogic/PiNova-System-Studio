PiNova website (static files)

Files in this folder make the small product/download website.

Before publishing:
1. Edit site-config.js.
2. Set githubRepository to your GitHub owner/repository, e.g. "pawan123/PiNova-System-Studio".
3. Set version to the release tag you want to display, e.g. "v5.1.0".
4. Upload the whole website folder to GitHub Pages or any static web host.

By default, download buttons point to GitHub Releases. If you want to upload
installer archives to the same web host yourself, create a `downloads` folder
next to index.html, put the exact release files there, and set:
  downloadBaseUrl: "./downloads/"
The file names must match the data-asset values used in index.html.

The GitHub Releases files are created by the included project workflow after a
version tag is pushed and the cross-platform build finishes.
