# V4.0 活动报名流程设计

适用版本：`V4.0`

更新时间：2026-03-19

## 1. 前台流程

1. 用户进入活动详情页 `/events/<id>`
2. 点击“报名”活动，进入 `/events/<id>/register`
3. 填写报名表单并提交 `POST /events/<id>/register`
4. 成功后跳转 `/events/<id>/register/success`

## 2. 表单字段（MVP）

- 姓名 `name`（必填）
- 学号 `student_id`（建议必填）
- 联系方式 `contact`（必填）
- 备注 `notes`（选填）

安全字段（后端记录）：
- `source_ip`
- `user_agent`

## 3. 后台处理流程

1. 管理员在 `/manage/event-registrations` 查看报名
2. 默认状态 `pending`
3. 审核后可改为 `confirmed/rejected`
4. 记录 `review_note`, `reviewed_by`, `reviewed_at`

## 4. 成功/失败与重试策略

- 成功：跳转成功页，展示活动标题与返回入口
- 表单校验失败：原页提示错误并保留用户输入
- 限流触发：返回“稍后再试”并给出 retry 秒数

## 5. 反滥用策略

- IP 维度限流（固定窗口）
- 基础内容长度校验
- 非法字段过滤（去除控制字符）

## 6. 导出需求预留

- CSV 导出放入 V4.4
- V4.0 仅保留数据结构与状态字段，避免后续迁移破坏
