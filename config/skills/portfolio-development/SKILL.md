---
name: portfolio-development
description: Find and run the appropriate toolchain and project checks for the owner's GitHub projects, including Roblox, Android, Godot, web, video and Production-OS.
---

Run `portfolio-doctor` from the project directory to identify repository signals and installed tools. Read the current repository's AGENTS.md, manifests, and relevant CI workflow before choosing versions or commands. Follow its documented checks after editing. For repositories adopting repo-standards, start with their bounded .ai context as directed by their AGENTS.md.

- Roblox: use the declared Rojo version, compile Luau, and run the existing project scripts. Studio playtests and releases use the repository's Studio or Roblox workflow and require the owner's authorized credentials.
- Godot: use the engine version expected by the project. Use `godot-4.5.1` for Jumpy Frog and `godot-4.6` for Jelly Bricks. Verify imports and scripts in headless mode. Use the repository's Android or Play build workflow for exports.
- Android: follow Gradle and SDK versions in the project workflows. Use the repository's GitHub Actions pipeline for emulator, Android SDK, keystore and Play release steps when unavailable locally.
- Web: use the repository's lockfile and run its browser checks. Daeu-b tests Chromium with a mobile viewport. Use an isolated browser verification on the VPS or the existing browser workflow.
- Video and 3D: check FFmpeg and FFprobe before rendering. Use Blender for scenes and geometry on the VPS. Use each project's own Python environment, existing media pipeline and GPU runner for large model workloads.
- Python packages: isolate dependencies with uv. Production-OS expects Python 3.12. Use `uv venv --python /opt/python312/bin/python3.12` inside the repository.
