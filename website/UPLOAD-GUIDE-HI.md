# Website upload karne ka tareeqa (Hindi)

Yeh website plain HTML/CSS/JavaScript hai; ise kisi server ya database ki zaroorat nahi.

## GitHub Pages par free publish karna

1. GitHub par login karo aur PiNova project ke repository ko open karo.
2. Project ki `website/site-config.js` file kholo aur Edit button dabao.
3. `YOUR-GITHUB-USERNAME/PiNova-System-Studio` ko apne exact GitHub username/repository se replace karo. Example: `pawan123/PiNova-System-Studio`.
4. Commit changes dabao.
5. Repository mein **Settings → Pages** kholo.
6. Build and deployment ke Source mein **GitHub Actions** select karo.
7. **Actions** tab mein `Publish PiNova website` workflow successful hona chahiye.
8. Settings → Pages par website URL mil jayega. Use public ke saath share kar sakte ho.

## Downloads kaise dikhte hain

Is project ka `Build PiNova releases` workflow Windows, Mac Intel/Apple Silicon, Linux aur Raspberry Pi ARM64 packages banata hai. Files publish karne ke liye code push hone ke baad version tag push karo:

```bash
git tag v5.1.0
git push origin v5.1.0
```

GitHub Actions tab mein build jobs successful hone par Release banega aur website ke Download links kaam karne lagenge. Release workflow complete hone se pehle download links ready nahi honge.

## Agar sirf website alag host karni hai

`website` folder ke andar `index.html`, `style.css`, `site.js`, `site-config.js`, aur `assets` folder ko ek saath host par upload karo. Sirf `index.html` upload mat karna — CSS, JS aur icon bhi chahiye.

## Apni hosting par files seedha upload karna

Agar releases ke badle apne hosting server se downloads dene hain, `website/downloads/` folder banao, har platform ki archive usmein upload karo, aur `site-config.js` mein `downloadBaseUrl: "./downloads/"` set karo. Filenames website ke Download buttons jaise hi hone chahiye.
