# 个人吃喝 LLM Wiki：证据摄入与编译工作流

这是对路边摊 Pro 原有算价能力的补充。**微信、飞书、点评软件、地图、社交媒体、相机照片、朋友推荐、本人到店感受都是素材来源**。不要在无授权时抓取聊天记录或浏览用户私人账号；只处理用户主动提交的材料。

## 核心规则

1. **先判别内容意图**：截图是菜品菜单、商家信息、他人评论、本人点单记录，还是仅供收藏？一个来源可以包含多种事实，但**不能凭截图就断言用户亲自到访、偏爱某店、已经下单**。
2. **Vision 提取与结构化**：WorkBuddy/ChatGPT 的具备图像理解能力的模型负责读图片；`scripts/wiki_store.py` 不包含 OCR，不会从二进制自行读出字。识别不清的商家、价格、时间、口味、位置标 `tentative` 或留空，不能凭空补足。
3. **Evidence First**：按来源永久保存提取结果、原文摘录/引用、日期、source_id。图片文件如果工作环境提供实际本地路径，可通过 `--media-file` 复制到本地证据库；否则只保存来源引用和已识别文字，务必说明**图片原件未归档**。敏感群头像、手机号、付款码不应作为偏好字段记入 Wiki。
4. **Compile**：商家有明确身份时生成 `~/.roadside-stall/wiki/pages/<vendor_id>.md`，每个描述可追溯 `source_id`。没有确定店铺就存到 `unassigned_sources`，不要臆造新店名、地址或商家 ID。页面只是派生结果，可以从来源记录重建。
5. **Lint**：重复截图不重复摄入；同一图片二次提取存在差异则报冲突，不静默覆盖。不同日期的菜价冲突保留各自证据，不直接更新正式 `menu.json`；确认最新有效价格和计价单位后，仍走原有 `--menu-diff`、`--update-menu` 的规则。
6. **Taste Profile**：仅将用户本人明确陈述的“喜欢、不喜欢、去过、想去”等写入 `personal_feedback`；网友点赞、平台星级、商品照片与收藏不等于用户偏好。可结合这些偏好回答“附近哪家比较适合我”，回答时说明依据、缺失信息及尚未验证的部分。
7. **订单安全**：知识摄入绝不能自动下单、改变 `orders.json` 或计入消费。算价仍使用 `stall_calc.py`，经用户确认实际下单才 `--confirm-order`。
8. **云端边界**：数据保存在执行脚本的 `ROADSIDE_STALL_HOME`，移动端云端和 Mac 本地不会凭空同步。知识库存储必须持久化；如果云端每次换运行环境，不可声称已经记住商家信息。

## 分辨常见图片

| 输入 | 处理策略 |
|---|---|
| 微信或飞书聊天截图，有多人明确点单 | 提取消息人、菜品、数量、增改单；去重后通过确定性脚本算价，除非用户要求收藏，也可存为 Wiki 来源；截图里的已过时订单不重新算入当前订单 |
| 某软件里的店铺页面截图 | 保存店名、可能的地址/菜系、截图来源和待核实推荐，不自动标记用户到访 |
| 路过拍的招牌或门面 | 建档线索，只有可读店名/位置才填；不要根据照片推断具体街道 |
| 菜单照片 | 提取能确认的品名、价格、单位。缺失字段标待核实，**不自动覆盖正式菜单** |
| 菜品实拍 | 无商家关联时存证据箱；用户明确描述感受才写入个人喜好 |
| 用户说“我吃过，喜欢清淡不油腻” | 记录用户明确偏好与到访事实，关联相应店铺；不知道是哪家时偏好仍可记录在来源证据中 |

## 输入格式（Agent 内部 JSON）

用户无需亲自写 JSON。收到图片或文字，模型先读证据再调用脚本。示例：

```json
{
  "source": {
    "kind": "store_screenshot",
    "origin": "用户手动上传：地图店铺截图",
    "source_key": "截图的稳定唯一标识或文件SHA256",
    "ref": "attachment://example",
    "excerpt": "截图可读：店名老街米线、地点上海徐汇、招牌番茄米线",
    "captured_at": "2026-11-05T13:20:00"
  },
  "entity": {
    "vendor_id": "lao-jie-mi-xian",
    "name": "老街米线",
    "city": "上海",
    "address": "",
    "cuisine": "米线"
  },
  "observations": [
    {"category":"product", "value":"菜单截图有番茄米线", "certainty":"confirmed", "voice":"unknown"},
    {"category":"taste", "value":"他人评论说汤底不错", "certainty":"tentative", "voice":"third_party"}
  ],
  "personal_feedback": {"explicit":false, "visit_status":"unknown", "preferences":[]}
}
```

来源类别 `source.kind`: `wechat_screenshot`、`chat_screenshot`、`store_screenshot`、`menu_photo`、`food_photo`、`map_screenshot`、`review_screenshot`、`text`、`other`。事实类别 `observations[].category`: `menu`、`price`、`taste`、`environment`、`service`、`location`、`opening_hours`、`product`、`contact`、`other`。`certainty` 为 `confirmed` 或 `tentative`，`voice` 为 `user`、`third_party` 或 `unknown`。

`personal_feedback` 只接受本人明确表达；`explicit=true` 时 `source.excerpt` 必须包含用户原话。

## 命令示例

以下命令中 `<skill_dir>` 为技能目录的绝对路径；数据放在执行环境的 `~/.roadside-stall/wiki/`。

```bash
# 摄入已解析素材；提供本地真实图片路径时自动保存证据图片
python3 <skill_dir>/scripts/wiki_store.py --ingest-file /tmp/wiki-input.json --media-file /tmp/shop-photo.png

# 无图片实体路径也可保存提取的来源事实；但不能声称图片原件已归档
python3 <skill_dir>/scripts/wiki_store.py --ingest-file /tmp/wiki-input.json

# 查看整个知识库、本人明确记录的口味、查询店铺
python3 <skill_dir>/scripts/wiki_store.py --list
python3 <skill_dir>/scripts/wiki_store.py --preferences
python3 <skill_dir>/scripts/wiki_store.py --find 番茄
python3 <skill_dir>/scripts/wiki_store.py --vendor lao-jie-mi-xian

# 任何时候都能从来源重新编译 Wiki 页面
python3 <skill_dir>/scripts/wiki_store.py --rebuild
```

## 对话输出

新截图入库后，简短告知：识别出的店铺、可靠事实、待核实信息、是否已真正保存图片文件、有没有写入个人偏好。推荐时先查 Wiki、列出证据和偏好匹配依据；**不因用户想去就虚构消费或真实到店记录**。
