# 路边摊 Pro · Platform Installation / 多平台安装

[English summary](../README.en.md) · [中文说明](../README.md)

This repository has **one implementation** and **two package formats** because WorkBuddy requires extra top-level YAML metadata. In both versions, the Python logic, Wiki rules and user data layout are the same.

本项目维护一套业务逻辑，生成两种不同的安装包：WorkBuddy 版使用扁平展示字段；Codex / Claude Code / OpenClaw / Hermes 使用标准 Agent Skills 描述。**不要导入旧 v2.2.1 安装包**，该版本的嵌套 frontmatter 会造成 WorkBuddy 注册失败。

## Requirements / 运行要求

- Python 3, local file read/write and permission to execute local scripts.
- The host model must support images to interpret screenshots; the bundled scripts do not perform OCR.
- Data is stored in `~/.roadside-stall/` or in the path specified by `ROADSIDE_STALL_HOME`. Different machines and agents do not automatically sync their Wiki or orders.
- Source files and user data are separate. Back up existing data before upgrading.

## WorkBuddy

Import `dist/workbuddy/skill.zip` into WorkBuddy via its Skill import UI. The ZIP contains one top-level `roadside-stall-pro/` directory and a `SKILL.md` whose `name`, `description`, `display_name`, `display_name_en`, `description_zh`, `description_en`, `examples_zh`, `version`, and `author` are **top-level YAML fields**. No `metadata:` nesting, no `__pycache__` or `.pyc`.

Importing a ZIP is not proof of registration. Check the Skill is still present in WorkBuddy's list after import, and that its version is v2.2.2.

Official documentation: https://open.workbuddy.cn/docs/skill

## Codex

Default personal Skill directory: `~/.agents/skills/`.

```bash
python3 scripts/install_local.py --targets codex
python3 scripts/install_local.py --targets codex --apply
```

## Claude Code

Personal Skill directory: `~/.claude/skills/`. Project Skills may be stored in `<project>/.claude/skills/`.

```bash
python3 scripts/install_local.py --targets claude-code --apply
```

## OpenClaw

Typically uses `~/.openclaw/skills/`, with optional workspace Skill directories. Check your configured discovery precedence.

```bash
python3 scripts/install_local.py --targets openclaw --apply
```

## Hermes Agent

Common personal Skill directory: `~/.hermes/skills/`; custom external directories may be configured.

```bash
python3 scripts/install_local.py --targets hermes --apply
```

## Install several clients / 同时安装

```bash
python3 scripts/install_local.py --targets codex claude-code openclaw hermes
python3 scripts/install_local.py --targets codex claude-code openclaw hermes --apply
```

By default the installer only previews. With `--apply`, it takes a snapshot of an existing Skill and copies a new version; it never deletes `~/.roadside-stall/`.

## Doubao / 豆包

A Doubao developer or enterprise integration may accept a ZIP Skill package, but consumer chat support for arbitrary Agent Skills **cannot be assumed**. Installation, sandbox execution, storage and publishing require separate platform verification.

## Validation / 验收

1. Verify Skill discovery and actual loading, not merely successful upload.
2. Verify Python execution and read/write permission to the data directory.
3. Test OCR-like image interpretation through the host model; do not misrepresent the Python scripts as image recognition software.
4. Test a menu image in **recognize-only** mode; it must not create an order or mark spending without confirmation.
5. Validate that old vendor, order and Wiki data remain intact after an upgrade.
