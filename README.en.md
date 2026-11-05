# Roadside Stall Pro · 路边摊 Pro

> A little human warmth growing on the digital streets. A personal food-and-places LLM Wiki that learns from the screenshots, menus, conversations and experiences you choose to share — and a practical assistant for calculating group food orders.

[中文 README](README.md) · [Skill instructions](SKILL.md) · [Installation guide](references/platform-install.md)

## Why I built this

I've recently been spending a lot of time in Zibo because of work.

I spent years working in Shanghai — a city of gleaming skyscrapers, bright lights, and people who always seem to be in a hurry. Walking through all that glitter, I sometimes caught myself thinking:

**Shanghai's prosperity belongs to Shanghai. It doesn't necessarily belong to me, just another person working there.**

I didn't expect to be moved by a very different kind of bustle in Zibo.

It began with a tiny roadside barbecue stall near my workplace: **Kun Ge Roadside BBQ (坤哥路边烧烤)**.

When I first saw its red price board, my Shanghai-trained sense of prices almost stopped working. Mutton skewers for two yuan, beef skewers for two yuan, pork belly for barely more than one. Could that really be right?

Then I discovered something even more surprising: Zibo was full of lively WeChat groups. People sold barbecue, fruit and all kinds of everyday food. A stall owner would post a picture; regulars would reply, add to their orders, change their minds, or pick up something for coworkers.

No glossy app, no grand business model. **A phone, a group chat, and a few shouted offers were enough to make a warm, very real little business work.**

We often assume technology is making everything more virtual and impersonal. But here, messages on a screen led to real streets, real people and food sizzling over charcoal. Digital orders were woven straight into neighborhood life.

**This is everyday human warmth growing on the digital network.**

And it seemed almost ready to spill out of the screen.

I loved that feeling.

So I wanted to use the AI technology I knew to do something with it. First, I wanted to untangle group barbecue orders. Then I thought: why not remember these little stalls, their menus and prices, friends' recommendations, places I'd tried, and what I actually liked?

That's how **Roadside Stall Pro** grew from an order calculator into a personal food Wiki — a small, evidence-based memory of the places and experiences that make a city feel like home.

**I want AI to find menus for me, quickly and intelligently sort out orders, and estimate the cost.**

**And I want to use a little digital technology to hold on to the everyday warmth that's almost overflowing from the screen.**

---

## What it does

- **Personal food Wiki:** capture merchants, menus, prices, recommendations and personal taste notes from text and screenshots, preserving evidence and uncertainty.
- **Menu and price checks:** keep prices separate by vendor; do not guess unreadable values, units or unknown current prices.
- **Group orders:** interpret people, dishes, quantities and corrections, then calculate totals deterministically with Python.
- **Drafts versus real purchases:** saving an order draft does not automatically count it as spending.
- **Privacy by design:** only content you deliberately share is processed; no automated WeChat collection, payments or message sending.

## Install

This repository provides a single core implementation with platform-specific frontmatter:

| Platform | Package or source |
| --- | --- |
| WorkBuddy | [WorkBuddy ZIP](https://raw.githubusercontent.com/xxjjjj/roadside-stall-pro/main/dist/workbuddy/skill.zip) — flat WorkBuddy YAML metadata |
| Codex, Claude Code, OpenClaw, Hermes Agent | [Portable ZIP](https://raw.githubusercontent.com/xxjjjj/roadside-stall-pro/main/dist/portable/skill.zip) or repository root — standard Agent Skills metadata |
| Doubao | Depends on its platform submission and review process; direct import is not guaranteed |

See the [Chinese platform-specific installation guide](references/platform-install.md) for details. The included Python scripts use the standard library; image understanding comes from the host agent, not from a bundled OCR engine.

Local data is stored separately under `~/.roadside-stall/` (or `ROADSIDE_STALL_HOME`). Never publish actual private group chats, personal orders, secrets, or unmasked payment QR codes.

## Run tests

```bash
python3 -m unittest discover -s tests -v
```

## License

[MIT](LICENSE). Contributions are welcome. Please respect merchants' and customers' privacy, verify prices independently, and do not treat the included menu as a live price guarantee.