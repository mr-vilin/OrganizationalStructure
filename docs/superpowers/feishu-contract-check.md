# 飞书组织系统 API 契约核验

> 核验日期：2026-09-15  
> 核验对象：`同步与接口设计.md` 涉及的登录、通讯录覆盖、六类事件和生命周期判定。  
> 一手依据：仓库内官方 Python SDK `lark-oapi==1.7.3` wheel，以及飞书开放平台、LarkSuite 官方 GitHub 仓库。本文没有连接真实企业。

> 来源边界：本次工具能打开飞书官方页面 URL，但多处动态正文无法稳定提取。接口路径、token 类型和字段以本地官方 SDK 为确认依据；依赖网页说明的授权语义均保留官方 URL，并在无法由 SDK 独立证明处标为“需真实联调”，不把搜索摘要或第三方镜像升级为已确认契约。

## 结论摘要

| 主题 | 结论 | 状态 |
| --- | --- | --- |
| Web 登录 | 授权入口、OIDC code 换 token、用用户 token 取 `user_info` 的接口契约可由官方 SDK 确认；`user_info` 模型包含 `open_id`、`user_id`、`union_id`、`tenant_key` | 已确认 |
| 组织绑定 | 首次成功登录可取得 `tenant_key`，可作为“登录者所在租户”的校验值；仍需用目标企业真实账号验证返回非空、同租户稳定以及管理员账号映射 | 需真实联调 |
| 全企业覆盖 | `GET /contact/v3/scopes` 只返回授权范围入口 ID，没有 `is_all_members` 一类字段；单凭返回数组不能可靠证明配置为“全部成员” | 已确认限制 |
| 无部门人员 | SDK 中 `GET /contact/v3/users` 与 `GET /contact/v3/users/find_by_department` 都带 `department_id`，官方说明均为按部门取直属用户；未找到可证明能够枚举所有无部门人员的 Contact v3 全员接口 | 未确认能力，需真实联调/产品配置核查 |
| 六类事件 | 六种事件名、P2 header 的 `event_id`、`tenant_key`、`app_id`，以及对象 ID 字段均可由 SDK 确认 | 已确认 |
| 删除/离职 | “全量中缺席”或单次详情不可读都不足以判定失效；应以租户/应用匹配的删除事件、事件状态字段和覆盖未收窄的独立证据组合判定 | 已确认设计边界；错误码仍需联调 |

## 1. OAuth 与租户身份

### 已确认

1. Web 授权入口为：

   ```text
   https://open.feishu.cn/open-apis/authen/v1/index
     ?app_id=<APP_ID>
     &redirect_uri=<URL_ENCODED_REDIRECT_URI>
     &state=<OPAQUE_STATE>
   ```

   官方维护的旧版 Python 封装仍以该路径生成登录 URL；官方 Web 应用示例也要求先在开发者后台把回调地址加入 Redirect URL 白名单。`state` 应生成一次性随机值并在回调时严格比对，用于防止登录 CSRF；`redirect_uri` 必须按 URL 查询参数编码，不能直接拼接任意用户输入。

2. 当前 wheel 的 OIDC code 交换接口是：

   - `POST /open-apis/authen/v1/oidc/access_token`
   - 使用应用身份 token（SDK 标记为 `AccessTokenType.APP`）
   - body：`grant_type`、`code`
   - response：`access_token`、`refresh_token`、`token_type`、`expires_in`、`refresh_expires_in`、`scope`

3. 用户信息接口是：

   - `GET /open-apis/authen/v1/user_info`
   - 使用上一步得到的用户 access token（SDK 标记为 `AccessTokenType.USER`）
   - response 模型包含 `open_id`、`union_id`、`user_id`、`tenant_key`、`employee_no` 等字段

4. 本系统应至少把 `tenant_key` 与配置连接绑定，并同时核对事件 header 的 `tenant_key`、`app_id`。`open_id` 只在同一应用内比较；通讯录同步采用 `user_id` 时，应保存登录返回的同应用 `open_id ↔ user_id` 映射。

### 未知或需真实联调

- 官方 SDK 只证明响应模型允许 `tenant_key`，不能证明目标租户和所申请 scope 下一定返回非空值。需用目标企业管理员和普通员工各登录一次确认。
- 授权 code 的实际有效期、是否一次性、用户拒绝授权的回调参数、refresh token 轮换行为应按目标应用配置联调，不应写死为 SDK 模型未表达的数值。
- 需要在真实环境验证回调白名单的精确匹配规则、HTTPS 生产域名和反向代理后的外部 URL。

### 精确来源

- wheel：`lark_oapi/api/authen/v1/model/create_oidc_access_token_request.py`
- wheel：`lark_oapi/api/authen/v1/model/create_oidc_access_token_request_body.py`
- wheel：`lark_oapi/api/authen/v1/model/create_oidc_access_token_response_body.py`
- wheel：`lark_oapi/api/authen/v1/model/get_user_info_request.py`
- wheel：`lark_oapi/api/authen/v1/model/get_user_info_response_body.py`
- [飞书官方 Web 应用登录示例](https://github.com/larksuite/lark-samples/tree/main/web_app_with_auth/python)
- [LarkSuite 官方旧版 OAuth 封装（明确授权 URL）](https://github.com/larksuite/feishu/blob/master/feishu/api_oauth.py)
- [飞书开放平台：获取 OIDC access token](https://open.feishu.cn/document/server-docs/authentication-management/login-state-management/get-oidc-access-token)
- [飞书开放平台：获取登录用户信息](https://open.feishu.cn/document/server-docs/authentication-management/login-state-management/get-user-info)

## 2. `contact/v3/scopes`、全企业覆盖与无部门人员

### 已确认

1. `GET /open-apis/contact/v3/scopes` 只能使用 tenant access token。请求支持 `user_id_type`、`department_id_type`、`page_token`、`page_size`；响应是分页的 `department_ids`、`user_ids`、`group_ids`、`has_more`、`page_token`。
2. 官方权限说明明确区分“应用可用范围”和“通讯录权限范围”。以应用身份调用通讯录 API 时，应在开发者后台把通讯录数据权限配置为“全部成员”，并发布、审核生效。
3. 官方说明：配置为全员时，scope 接口返回企业所有一级部门；非全员时，返回管理员勾选的部门、用户或用户组，且勾选部门的子部门不直接出现在 scope 响应中。因此必须完整翻页，随后从返回入口递归遍历子部门。
4. scope 响应没有“全员/部分”的显式字段。部分授权也可能人工勾选出与一级部门集合看似相同的结果，所以数组内容本身不能作为全员覆盖的密码学式或确定性证明。
5. wheel 同时包含两个人员列表请求：

   - `GET /open-apis/contact/v3/users`
   - `GET /open-apis/contact/v3/users/find_by_department`

   二者模型均有 `department_id`，官方目录将它们描述为基于部门 ID 获取直属用户。官方组合示例也是“递归部门 + 每部门直属用户 + 去重”，没有全员或无部门人员补集步骤。

### 可执行的覆盖验收规则

只有同时满足下列条件，系统才可把本轮标为“组织树范围完整”；“所有自然人完整”还要额外通过无部门人员联调：

1. 使用 tenant access token 调用 scopes 并遍历所有分页，无任何页失败。
2. 运维侧保存本次应用版本已经发布且通讯录数据权限为“全部成员”的人工验收记录；API 响应不能替代这项配置事实。
3. 以企业根节点执行子部门遍历成功，所有页完成；每个 scope 入口均能解析，所有父链闭合。
4. 每个部门的直属用户分页成功；对重复 `user_id` 去重，并回查完整部门关系。
5. 订阅并处理通讯录权限范围变更事件；一旦范围变化，立即把覆盖状态降为 `unknown/incomplete`，暂停基于缺席的失效判定，重新执行 scope 与全量核验。

### 无部门人员结论

当前一手契约不足以确认“递归所有部门”能覆盖无部门人员。`department_id` 在 Python 类型上是 `Optional` 也不代表服务端允许省略；生成模型不会表达所有服务端必填约束。开发时不得把“不传 department_id 调 `/contact/v3/users`”当成已确认方案。

需在目标企业建立或找到一个明确无部门的测试账号，至少验证：

- scopes 的 `user_ids` 是否会显式列出该账号；
- 企业根部门 ID 调人员列表时是否返回该账号；
- `/contact/v3/users` 省略 `department_id` 是返回全员、报参数错误，还是采用默认部门；
- 入职、移出最后一个部门和离职时，六类事件分别如何触发。

若三种枚举方式均不能稳定发现无部门人员，首版必须把覆盖状态表述为“部门树内人员完整”，不能表述为“全企业人员完整”；需要另行采用飞书官方确认的人员主数据接口或业务上禁止无部门在职人员。

### 精确来源

- wheel：`lark_oapi/api/contact/v3/model/list_scope_request.py`
- wheel：`lark_oapi/api/contact/v3/model/list_scope_response_body.py`
- wheel：`lark_oapi/api/contact/v3/model/list_user_request.py`
- wheel：`lark_oapi/api/contact/v3/model/find_by_department_user_request.py`
- [飞书开放平台：权限范围资源介绍](https://open.feishu.cn/document/server-docs/contact-v3/scope/overview)
- [飞书开放平台：获取通讯录授权范围](https://open.feishu.cn/document/server-docs/contact-v3/scope/list)
- [飞书开放平台：获取部门直属用户列表](https://open.feishu.cn/document/server-docs/contact-v3/user/find_by_department)
- [LarkSuite 官方组合示例：获取部门下所有用户](https://github.com/larksuite/oapi-sdk-python-demo/blob/main/composite_api/contact/list_user_by_department.py)

## 3. 六类事件载荷、ID 与租户身份

### 公共 P2 header

六类事件都继承 `EventContext`。P2 header 模型包含：

- `event_id`：事件幂等键；
- `event_type`：应与注册的事件类型一致；
- `create_time`：用于观测乱序和迟到，不能单独决定覆盖新状态；
- `tenant_key`：必须等于连接绑定租户；
- `app_id`：必须等于当前配置应用；
- `token`：回调校验相关字段；长连接由 SDK 分发时仍应执行上面的租户、应用和事件类型业务校验。

事件注册名已由官方 SDK dispatcher 确认：

| 事件 | `event.object` / `old_object` | 可依赖的对象标识 |
| --- | --- | --- |
| `contact.department.created_v3` | `object: DepartmentEvent` | `object.open_department_id`；模型也含 `department_id` |
| `contact.department.updated_v3` | `object` + `old_object: DepartmentEvent` | 新对象 `open_department_id`；两份载荷用于识别变化但最终仍回查 |
| `contact.department.deleted_v3` | `object: DepartmentEvent` + `old_object: OldDepartmentObject` | `object.open_department_id`；旧对象也含 `open_department_id` |
| `contact.user.created_v3` | `object: UserEvent` | `object.user_id`；也含 `open_id`、`union_id` |
| `contact.user.updated_v3` | `object` + `old_object: UserEvent` | `object.user_id`，并保留 `open_id` 作为同应用映射 |
| `contact.user.deleted_v3` | `object: UserEvent` + `old_object: OldUserObject` | 优先 `object.user_id`；旧对象只保证模型可承载 `open_id` 和 `department_ids` |

`DepartmentEvent.status` 可承载 `is_deleted`；`UserEvent.status` 可承载 `is_resigned`、`is_exited` 等状态。字段“存在于 SDK 模型”不保证目标权限下每次事件都返回，因此接收器必须允许字段缺失，持久化原始必要字段，并以对象 ID 发起权威回查。

### 需真实联调

- 事件中 `department_id` 的具体 ID 类型不能仅凭字段名判断；本系统既然统一使用 `open_department_id`，应明确取该字段，并验证回查参数 `department_id_type=open_department_id`。
- 验证用户删除事件的 `object.user_id` 在真实离职场景是否总是存在，以及重新入职是否复用 `user_id`。
- 验证只变更主部门时是否触发 `contact.user.updated_v3`，`orders` 是否在事件中完整返回。
- 验证长连接重复投递、乱序、断线期间补投范围；不能承诺事件恰好一次或无限期补投。

### 精确来源

- wheel：`lark_oapi/event/context.py`
- wheel：`lark_oapi/event/dispatcher_handler.py`
- wheel：`lark_oapi/api/contact/v3/model/p2_contact_{department,user}_{created,updated,deleted}_v3.py`
- wheel：`lark_oapi/api/contact/v3/model/department_event.py`
- wheel：`lark_oapi/api/contact/v3/model/old_department_object.py`
- wheel：`lark_oapi/api/contact/v3/model/user_event.py`
- wheel：`lark_oapi/api/contact/v3/model/old_user_object.py`
- wheel：`lark_oapi/api/contact/v3/model/department_status.py`
- wheel：`lark_oapi/api/contact/v3/model/user_status.py`
- [飞书开放平台：部门事件目录](https://open.feishu.cn/document/server-docs/contact-v3/department/events/created)
- [飞书开放平台：用户事件目录](https://open.feishu.cn/document/server-docs/contact-v3/user/events/created)

## 4. 可靠判定部门删除和员工离职

### 可以直接采用的规则

1. **绝不根据单次缺席判定失效。** 全量或子树结果未出现对象，可能来自分页失败、权限收窄、部门移动或接口暂时不可用。
2. **先校验事件归属。** 删除事件只有在 `header.app_id`、`header.tenant_key` 与已绑定连接一致，`event_id` 尚未处理，事件类型与载荷一致时，才进入生命周期候选。
3. **删除事件是强证据，但仍防迟到。** 收到 `department.deleted_v3` 或 `user.deleted_v3` 后回查当前对象：
   - 若详情成功且状态仍有效，以当前详情为准，事件记为迟到或对象已恢复；
   - 若详情成功且 `status.is_deleted` / `status.is_resigned`（或经真实联调确认的等价状态）为真，可确认失效；
   - 若详情不可读，只有在事件身份有效、对象 ID 匹配、当前 scope/根遍历仍证明覆盖未收窄且没有更新事件显示对象已恢复时，才可依据删除事件确认失效；否则标记 `pending_verification`。
4. **权限变化优先使判定降级。** scopes 失败、权限范围变更事件、根节点访问失败、关键分页失败或大量对象同时消失时，立即禁止任何“缺席即失效”的发布。
5. **恢复优先于旧事件。** 后续成功详情或创建/更新事件证明对象有效时，复用本地稳定 ID，恢复活动状态；`event.create_time` 仅辅助排序，最终事实来自最新成功回查。

### 仍需真实联调后固化

- `GET /contact/v3/users/:user_id` 与 `GET /contact/v3/departments/:department_id` 对“已删除”和“无权限”分别返回的 HTTP 状态、业务 `code`、`msg`。SDK 只给统一响应壳，不能证明具体错误码。
- 离职人员详情是否仍可读取、可读取多久，以及 `status.is_resigned`、`is_exited` 的业务差别。
- 部门删除后详情是否返回带 `is_deleted=true` 的对象，还是直接报不存在。
- `batch_get_id` 的 `include_resigned` 只支持已知邮箱/手机号查 ID，不能作为全员离职枚举；是否适合作为人工排障证据需用目标字段权限验证。

在这些错误码和保留行为未完成联调前，生产状态机应保留三态：`active`、`inactive_verified`、`pending_verification`，并在 `pending_verification` 保留最后已知业务事实，不结束当前关系。

### 精确来源

- wheel：`lark_oapi/api/contact/v3/model/get_user_request.py`
- wheel：`lark_oapi/api/contact/v3/model/get_department_request.py`
- wheel：`lark_oapi/api/contact/v3/model/batch_get_id_user_request_body.py`
- [飞书开放平台：获取单个用户信息](https://open.feishu.cn/document/server-docs/contact-v3/user/get)
- [飞书开放平台：获取单个部门信息](https://open.feishu.cn/document/server-docs/contact-v3/department/get)
- [飞书开放平台：通讯录权限范围变更事件](https://open.feishu.cn/document/server-docs/contact-v3/scope/events/updated)

## 5. 开发前必须完成的真实联调清单

1. 两类账号完成 OAuth：记录脱敏后的 `tenant_key`、`open_id`、`user_id` 是否存在和稳定。
2. 在开发者后台保存“通讯录数据权限 = 全部成员、版本已发布生效”的验收证据；随后完整调用 scopes，并测试权限收窄事件。
3. 准备普通部门、多部门、根级/无部门、离职、重新入职样本，验证分页、事件和详情响应。
4. 对部门删除、人员离职、部门移动、移出最后一个部门、权限撤回分别记录 HTTP 状态、业务 code、事件原始结构和后续详情结果。
5. 只有上述样本完成后，才把目标租户的具体错误码、状态字段和“无部门人员枚举方案”写入可执行状态机。

## 6. Python SDK 1.7.3 长连接 worker 集成边界

本节只依据 wheel 内 `lark_oapi/ws/client.py`、`lark_oapi/event/dispatcher_handler.py` 和 `lark_oapi/api/contact/v3/processor.py`。

### 已确认的执行模型

1. `ws.Client.start()` 是同步阻塞方法。它先对模块级 `loop` 调用 `run_until_complete(self._connect())`，再创建 ping task，最后执行 `run_until_complete(_select())`；`_select()` 是无限循环，每次休眠 3600 秒。因此 `start()` 正常运行时不会返回，也不能放进 Web 服务主线程或已有 asyncio event loop 所在线程。
2. event loop 在 `lark_oapi/ws/client.py` 模块导入时用 `asyncio.get_event_loop()` 取得；取不到才创建新 loop。它是模块级共享对象，不是每个 `Client` 独立持有。
3. 接收循环每收到一条消息就执行 `loop.create_task(self._handle_message(msg))`。在当前实现里，事件回调调用前没有让出 loop 的 `await`，所以普通同步回调在同一个 loop 线程中逐个执行；响应写回阶段会发生异步调度。这个实现细节仍不构成跨断线、重投或未来 SDK 版本的顺序保证。
4. 对事件帧，`_handle_data_frame()` 在该 asyncio loop 线程内直接同步调用 `self._event_handler._do_without_validation(pl)`。dispatcher 解析后调用 processor 的 `do()`；六类 Contact processor 的实现都是直接 `self.f(data)`，没有 `await`，注册类型也是 `Callable[..., None]`。
5. 因此注册回调必须是普通同步函数。注册 `async def` 只会返回 coroutine 对象，SDK 不会 await 它。同步回调如果执行数据库、HTTP、全量同步或等待队列，会阻塞同一个 loop，连带阻塞后续事件处理、ping 和应答。
6. `_handle_data_frame()` 只有在同步回调返回后才写回响应帧。回调抛异常时响应改为 HTTP 500 语义的 code；回调成功返回后才发送成功响应。因此收件回调只能完成快速、确定的校验和持久入箱/投递，不应执行远程回查。

### 推荐的 worker 结构

- 把长连接 client 放在独立 OS 进程中运行，进程内只运行一个 `ws.Client.start()`。这是 1.7.3 的阻塞和模块级 loop 设计下最稳妥的隔离方式，也避免与 ASGI/后台任务框架自己的 event loop 冲突。
- 六类同步回调只提取并校验 `event_id`、`event_type`、`tenant_key`、`app_id` 和对象 ID，然后以幂等方式写入持久 `event_inbox` 或调用线程安全、非阻塞的本地投递入口。耗时同步由另一个 worker 消费。
- 回调会在 SDK loop 所在线程执行；若投递到另一个 asyncio loop，必须使用目标框架提供的线程安全入口，不能在回调中直接操作属于另一 loop 的 async queue/session。若写数据库，连接/session 也必须符合其线程归属，并把事务限制在一次短入箱操作内。
- 数据库唯一键应约束 `event_id`，处理逻辑必须幂等。1.7.3 当前会在单个 loop 线程中逐个调用同步回调，但不要把这一实现细节当成业务顺序保证，也不要据此省略数据库幂等和乱序保护。

### 连接与重连通知

1. 1.7.3 `Client` 实例有两个公开命名的可赋值属性：

   - `on_reconnecting: Callable[[], None]`
   - `on_reconnected: Callable[[], None]`

   二者默认是空 lambda。SDK 在发现接收循环断开并进入 `_reconnect()` 时同步调用 `on_reconnecting()`；第一次重新连接成功后由 `_fire_on_reconnected()` 同步调用 `on_reconnected()`。hook 异常会被 SDK 捕获并记录，不会中止重连。
2. 这两个 hook 没有事件参数，也没有 builder/setter；它们是源码中明确提供给 higher-level wrapper 的 observer 属性。hook 与事件回调一样运行在 SDK loop 线程，必须立即返回。
3. `on_reconnected` 只表示断线后的 WebSocket 重新建立成功。首次 `_connect()` 成功不会调用它；源码也没有公开的 `on_connected` hook。
4. 可在 `on_reconnecting` 中把连接健康状态置为 `reconnecting/unknown`；可在 `on_reconnected` 中只投递一个幂等的“连接恢复后全量核对”任务。不要在 hook 内直接执行全量核对。
5. 启动成功没有 hook，且 `start()` 不返回。若业务必须准确获知首次连接完成，1.7.3 没有公开通知契约；不能读取 `_conn`、`_conn_id` 等私有字段作为稳定 API。可把进程存活标为 `starting`，待第一条合法事件或独立的通讯录探活/全量任务成功后再标记业务可用，或者先将“首次启动全量核对”作为独立任务安排，不依赖 WebSocket 首连通知。

### 退出与停止

1. 该 wheel 的 `Client` 没有公开 `stop()`、`close()`、`start_async()` 或 context manager。`_disconnect()` 是私有 async 方法。
2. 即使外部设法调用私有 `_disconnect()`，`start()` 仍阻塞在无限 `_select()`，ping task 也没有公开取消句柄，因此它不能构成受支持的完整停止流程。
3. 1.7.3 下不要把“优雅停止长连接”建立在私有 `_disconnect()` 或模块级 `loop` 上。应由进程管理器监督独立长连接进程：主服务停止时先停止新的业务消费并完成短事务，再按部署平台的正常进程终止流程结束长连接子进程；异常退出后由 supervisor 重启。
4. 因为没有公开停止确认，退出期间可能存在已收到但尚未成功入箱的事件。启动与每次 `on_reconnected` 后都应安排全量核对，事件收件箱保持幂等，不能把进程正常退出等同于“事件无遗漏”。

### 精确源码位置

- wheel：`lark_oapi/ws/client.py`：模块级 `loop`、`Client.start`、`_receive_message_loop`、`_handle_data_frame`、`_reconnect`、`_fire_on_reconnected`、`_disconnect`
- wheel：`lark_oapi/event/dispatcher_handler.py`：`EventDispatcherHandler._do_without_validation`
- wheel：`lark_oapi/api/contact/v3/processor.py`：六类 `P2Contact*V3Processor.do`
