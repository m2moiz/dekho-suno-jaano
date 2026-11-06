# Files Macroscope skips when it reviews a pull request.
#
# Docs: https://docs.macroscope.com/bug-detection-and-fixes#macroscope-ignore
# This file REPLACES Macroscope's built-in ignore list instead of adding to it,
# so the built-in list is copied first, verbatim from that page (fetched
# 2026-10-09). The repo's own additions are at the end.
#
# Test files are still skipped: test detection is a separate switch
# (`ignoreTests` front matter) that this file leaves at its default. CodeRabbit
# reviews the tests instead. See docs/review-bots.md.

# === Vendored / dependency directories ===
**/.git/**
**/__pycache__/**
**/.pytest_cache/**
**/.mypy_cache/**
**/.ruff_cache/**
**/venv/**
**/.venv/**
**/node_modules/**
**/site-packages/**
**/.pnpm-store/**
**/__Snapshots__/**
**/__snapshots__/**
**/.agents/skills/**
**/.claude/skills/**
**/.github/skills/**
**/bower_components/**
**/jspm_packages/**
**/.next/**
**/.svelte-kit/**
**/.nuxt/**
**/.output/**
**/.vercel/**
**/.angular/**
**/vendor/**
**/_vendor/**
**/third_party/**
**/Pods/**
**/.bundle/**

# === Root-anchored ambiguous directories ===
build/**
out/**
env/**
ENV/**

# === Generated / build-output directories (match anywhere) ===
**/target/**
**/dist/**
**/generated/**
**/intermediates/**
**/generated_sources/**
**/generated-sources/**
**/generated-src/**
**/src/main/generated/**

# === Minified build output ===
**/*.min.js
**/*.min.css
**/*.bundle.js

# === Yarn PnP loader files ===
**/.pnp.cjs
**/.pnp.loader.mjs

# === Generated protobuf / codegen files ===
**/*_pb.d.ts
**/*_pb.js
**/*.pb.go
**/*_pb2.py
**/*_pb2_grpc.py
**/*_pb2.pyi
**/*.grpc.swift
**/*.pb.swift
**/*.sql.go
**/*.designer.cs
**/*.g.dart
**/*.pb.dart
**/*_pb.rb
**/*.d.ts
**/*.gen.ts
**/*.gen.tsx
**/*.gen.js
**/*.gen.jsx

# === Package manager files ===
**/go.mod
**/package.json
**/*.pbxproj
**/*.xcstrings
**/*.strings
**/*.properties
**/pom.xml
**/Package.swift
**/bun.lock
**/.eslintrc
**/.eslintignore

# === Lock / sum files ===
**/go.sum
**/package-lock.json
**/pnpm-lock.yaml
**/yarn.lock
**/Package.resolved

# === Images ===
**/*.jpg
**/*.jpeg
**/*.png
**/*.gif
**/*.svg
**/*.ico
**/*.webp
**/*.bmp
**/*.tiff

# === Fonts ===
**/*.woff
**/*.woff2
**/*.ttf
**/*.eot
**/*.otf

# === Media ===
**/*.mp3
**/*.mp4
**/*.wav
**/*.avi
**/*.mov
**/*.mkv
**/*.flac
**/*.ogg
**/*.srt

# === Archives ===
**/*.zip
**/*.tar
**/*.gz
**/*.rar
**/*.7z
**/*.bz2

# === Documents ===
**/*.pdf
**/*.doc
**/*.docx
**/*.xls
**/*.xlsx
**/*.ppt
**/*.pptx

# === Data / serialized ===
**/*.db
**/*.sqlite
**/*.sqlite3
**/*.parquet
**/*.avro
**/*.arrow
**/*.npy
**/*.pkl
**/*.jsonl

# === ML models ===
**/*.onnx
**/*.tflite
**/*.h5
**/*.safetensors

# === Compiled / binary ===
**/*.exe
**/*.dll
**/*.so
**/*.dylib
**/*.bin
**/*.pyc
**/*.class
**/*.o
**/*.a
**/*.wasm

# === Certificates / keys ===
**/*.cer
**/*.pem
**/*.p12

# === Platform-specific / non-reviewable ===
**/*.stringsdict
**/*.snap
**/*.adoc
**/*.arb
**/*.lock
**/*.po
**/*.fbx
**/*.log
**/*.xib
**/*.meta
**/*.kml
**/*.prefab
**/*.eml
**/*.csv
**/*.grpc.reflection
**/*.js.map

# === dekho-suno-jaano additions ===
# The built page, written by `just ui-build`. Never hand-edited, and large:
# Macroscope bills per KB of diff reviewed (https://docs.macroscope.com/pricing).
dsj/ui/static/**
# Design critique notes and tracker state, not code.
.impeccable/**
.beads/**
# Prose. CodeRabbit reviews it against the repo's writing rules; Macroscope
# is kept on code correctness so the two do not pay twice for the same file.
**/*.md
# Working probes, not shipped code.
scratch/**
