# packaging/scripts/build-all.ps1
# Local script to orchestrate the build for testing

Write-Host "Building Backend (PyInstaller)..."
cd ../../backend
poetry run pyinstaller ../packaging/pyinstaller.spec --distpath ../packaging/dist --workpath ../packaging/build

Write-Host "Building Frontend..."
cd ../apps/desktop
npm run build

Write-Host "Packaging with Electron Builder..."
npx electron-builder --config ../../packaging/electron-builder.yml

Write-Host "Build complete! Check apps/desktop/release."
