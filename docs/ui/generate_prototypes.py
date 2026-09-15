"""生成用于设计评审的 SVG 原型；所有数据均为虚构示例。"""
from pathlib import Path
from html import escape

OUT = Path(__file__).resolve().parent
parts = []

def rect(x, y, w, h, fill='#ffffff', stroke='#e7eaf0', radius=8):
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}"/>')

def text(x, y, s, size=14, color='#263449', weight=400):
    parts.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}">{escape(str(s))}</text>')

def line(x, y, xx, yy):
    parts.append(f'<path d="M{x} {y} L{xx} {yy}" stroke="#e7eaf0"/>')

def button(x, y, label, primary=False, w=136):
    rect(x,y,w,34,'#1677ff' if primary else '#fff','#1677ff' if primary else '#d9dfe8',6)
    text(x+14,y+22,label,14,'#fff' if primary else '#334155')

def tag(x,y,label,color='blue'):
    colors={'blue':('#eaf3ff','#1677ff'),'green':('#edf9f0','#268344'),'orange':('#fff4df','#ad6800'),'gray':('#f1f3f6','#667085')}
    bg,fg=colors[color]; w=len(label)*14+18
    rect(x,y,w,25,bg,bg,4);text(x+9,y+17,label,12,fg)

def note(x,y,w,title,detail,warning=False):
    rect(x,y,w,64,'#fff8e8' if warning else '#f0f6ff','#ffe0a3' if warning else '#cfe1ff',6)
    text(x+16,y+24,title,14,'#925d12' if warning else '#285b9c',600)
    text(x+16,y+46,detail,12,'#697586')

def base(title, desc, active=0):
    parts.clear()
    parts.append('<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="900" viewBox="0 0 1440 900"><g font-family="Microsoft YaHei, PingFang SC, Arial, sans-serif">')
    rect(0,0,1440,900,'#f5f7fa','#f5f7fa',0);rect(0,0,208,900,'#fff','#e7eaf0',0)
    rect(20,22,32,32,'#1677ff','#1677ff',8);text(27,44,'组',19,'#fff',600)
    text(64,36,'组织服务',18, '#172b4d',600);text(64,54,'ORGANIZATION',9,'#98a2b3')
    for i,label in enumerate(['组织架构','门店管理','同步中心','变更日志','管理设置']):
        yy=105+i*52
        if i==active:rect(12,yy-25,184,42,'#eaf3ff','#eaf3ff',7)
        text(29,yy, ['◇','▦','↻','≡','⚙'][i],20,'#1677ff' if i==active else '#7b8798')
        text(62,yy,label,14,'#1677ff' if i==active else '#475467',600 if i==active else 400)
    line(20,789,188,789);tag(24,809,'单企业实例','gray');text(24,861,'内部管理工作台',12,'#98a2b3')
    rect(208,0,1232,64,'#fff','#e7eaf0',0);text(236,39,'示例餐饮集团',14,'#344054',600)
    text(1090,39,'设计原型 · 示例数据',12,'#98a2b3');tag(1270,21,'管理员','blue')
    text(236,98,'工作台  /  '+title,12,'#8b96a7');text(236,139,title,26,'#172b4d',600);text(236,167,desc,13,'#7b8798')
    text(236,879,'UI 评审稿  /  2026.09.15     ·     Python + React / Ant Design     ·     非实时业务数据',11,'#98a2b3')

def table(x,y,width,headers,rows,widths):
    rect(x,y,width,43,'#f8fafc','#f8fafc',0)
    offsets=[x+16]
    for w in widths[:-1]:offsets.append(offsets[-1]+w)
    for xx,h in zip(offsets,headers):text(xx,y+27,h,12,'#667085',600)
    for i,row in enumerate(rows):
        yy=y+43+i*57
        for j,(xx,v) in enumerate(zip(offsets,row)):
            text(xx,yy+33,v,13,'#1677ff' if j==len(row)-1 else '#344054')
        line(x,yy+57,x+width,yy+57)

def save(name):
    parts.append('</g></svg>');(OUT/name).write_text(''.join(parts),encoding='utf-8')

def organization():
    base('组织架构','查看飞书组织与人员，在本地维护门店标记。')
    note(236,192,1176,'通讯录覆盖完整 · 当前展示最近已提交数据','最近全量成功：今天 03:08   ｜   最近提交：10:24   ｜   数据版本：v42')
    rect(236,276,288,570);text(256,310,'部门目录',16,weight=600)
    rect(252,329,256,34);text(267,351,'搜索部门名称…',13,'#98a2b3')
    text(256,390,'□  独立选择节点',12,'#667085');text(256,426,'⌄  示例餐饮集团',14,weight=600)
    for y,label in [(466,'›  总部'),(506,'⌄  华东区域'),(548,'⌄  人民路店'),(590,'后厨组'),(632,'前厅组'),(674,'›  大学城店')]:
        if y==548:rect(248,523,264,40,'#eaf3ff','#eaf3ff',4)
        text(296 if label in ['后厨组','前厅组'] else 274,y,label,14,'#1677ff' if y==548 else '#475467')
    tag(417,533,'门店');tag(417,659,'门店');text(256,752,'选择父节点不会勾选后代',12,'#98a2b3');button(256,778,'批量设为门店',w=246)
    rect(544,276,868,219);text(568,312,'人民路店',20,weight=600);tag(688,292,'有效','green');tag(754,292,'门店')
    button(1080,292,'更新此部门及下级',w=176);button(1266,292,'编辑资料',w=124)
    text(568,351,'组织路径',12,'#8b96a7');text(679,351,'示例餐饮集团 / 华东区域 / 人民路店')
    text(568,388,'门店编码',12,'#8b96a7');text(679,388,'SH-001');text(936,388,'来源状态',12,'#8b96a7');text(1043,388,'有效 · 已核实')
    text(568,425,'备注',12,'#8b96a7');text(679,425,'门店资料由管理员维护');text(568,469,'部门名称、上级和人员关系来自飞书，仅支持同步查看。',12,'#98a2b3')
    rect(544,515,868,331);text(568,551,'部门人员',16,weight=600);tag(664,533,'去重 4 人','gray')
    button(1090,531,'直属人员',w=130);button(1230,531,'全部下级',True,w=158)
    table(560,576,836,['姓名 / 工号','主部门','主门店','数据质量','操作'],[
        ['张三 · E1024','后厨组','人民路店','已核实','查看详情'],['李敏 · E1025','前厅组','人民路店','已核实','查看详情'],['王晨 · E1026','人民路店','人民路店','已核实','查看详情'],['赵宁 · E1027','待核实','未知','主标识缺失','查看详情']], [167,162,160,176,139])

organization();save('01-organization.svg')
organization()
parts.append('<rect x="208" y="64" width="1232" height="794" fill="#152b49" opacity="0.24"/>')
rect(886,64,554,794,'#fff','#e7eaf0',0);text(912,104,'人员详情',18,weight=600);text(1399,104,'×',24,'#667085');line(886,126,1440,126)
rect(912,150,52,52,'#eaf3ff','#eaf3ff',26);text(925,184,'张',24,'#1677ff');text(984,172,'张三',23,weight=600);text(984,197,'E1024  ·  员工资料来自飞书',12,'#8b96a7');tag(1287,151,'在职','green')
text(912,244,'主部门',12,'#8b96a7');text(912,270,'华东区域 / 人民路店 / 后厨组',15)
text(912,315,'全部所属门店',12,'#8b96a7');tag(912,329,'人民路店');tag(1017,329,'大学城店')
text(912,395,'主门店',12,'#8b96a7');text(912,428,'人民路店',23,'#1677ff',600);tag(1055,406,'已解析','green')
line(912,453,1412,453);text(912,491,'归属依据',16,weight=600)
text(912,528,'01  主部门关系',13,'#667085');text(934,561,'后厨组  →  人民路店',16,weight=600);text(934,586,'沿主部门向上找到最近门店，确定为主门店。',12,'#8b96a7')
text(912,632,'02  兼职部门关系',13,'#667085');text(934,663,'大学城店  →  大学城店',16,weight=600);text(934,688,'部门本身是门店，计入全部归属。',12,'#8b96a7')
note(912,719,500,'主门店由飞书主部门派生','无法读取主部门时显示未知，不从兼职门店猜选。')
save('02-employee.svg')

base('门店管理','门店是明确标记的部门；人员归属按最近门店计算。',1)
for x,value,label in [(236,'3','有效门店'),(635,'6','门店归属员工（跨店去重）'),(1034,'1','跨店员工')]:
    rect(x,192,378,111);text(x+20,225,label,13,'#7b8798');text(x+20,273,value,32,weight=600)
rect(236,323,1176,333);rect(256,346,344,34);text(270,368,'搜索门店名称或编码',13,'#98a2b3');text(627,369,'□  包含失效记录',13,'#667085');button(1204,346,'去组织页标记',True,w=184)
table(252,402,1144,['门店 / 编码','组织路径','归属人数','主门店人数','状态','操作'],[
    ['人民路店 · SH-001','华东区域 / 人民路店','4','4','有效','编辑资料'],['大学城店 · SH-002','华东区域 / 大学城店','2','1','有效','查看人员'],['滨江店 · SH-003','华东区域 / 滨江店','1','1','有效','查看人员']], [250,300,135,150,120,157])
note(236,678,1176,'跨店员工会分别计入各家门店','各店归属人数之和为 7，跨店去重后为 6 人；企业总人数须按全体员工单独统计。')
text(256,789,'编辑资料：仅维护可选编码和备注。取消门店标记后，部门与历史资料保留。',14,'#667085')
save('03-stores.svg')

base('同步中心','查看同步健康、执行范围和异常；失败时保留最后成功数据。',2)
button(1228,119,'一键全量更新',True,w=184)
for x,title,value,sub,color in [(236,'飞书连接','已连接','连接检测：10:25','green'),(536,'通讯录范围','覆盖不完整','权限范围变化待核实','orange'),(836,'最近全量成功','今天 03:08','数据仍来自成功版本 v42','blue'),(1136,'最近事件处理','10:24','事件空闲不等于断线','gray')]:
    rect(x,192,276,124);text(x+18,222,title,13,'#7b8798');text(x+18,258,value,22,'#ad6800' if color=='orange' else '#172b4d',600);text(x+18,291,sub,12,'#8b96a7')
note(236,336,1176,'当前覆盖检查异常 · 已保留上一份成功数据','请核查飞书通讯录权限；不会把不可读的部门或员工标记为删除、离职。',True)
rect(236,420,1176,173);text(258,453,'当前任务  #SYNC-1043',16,weight=600);tag(490,435,'执行中');text(1106,453,'手动全量  ·  已耗时 00:42',13,'#667085')
for x,label,selected in [(264,'1  采集与回查',True),(552,'2  覆盖与关系校验',False),(851,'3  事务发布',False),(1150,'4  结果摘要',False)]:
    tag(x,482,label,'blue' if selected else 'gray')
text(258,558,'正在采集：已处理 126 个部门、842 位员工；总量待确认。',14,'#667085')
rect(236,613,1176,234);text(258,650,'最近任务',16,weight=600)
table(252,668,1144,['任务 / 类型','范围','阶段 / 结果','时间','操作'],[
    ['#1042 · 按部门更新','人民路店及全部后代','失败 · 权限不足','10:20','失败详情 / 重试'],['#1041 · 每日核对','全企业','成功 · 无内容变更','03:08','查看结果']], [255,275,275,140,199])
save('04-sync.svg')

base('变更日志','追踪已观察到的变化、来源和提交时间。',3)
rect(236,192,1176,433)
for x,label,w in [(256,'对象名称或 ID',250),(526,'全部操作类型  ⌄',210),(756,'操作者 / 任务',220),(996,'选择时间范围',220)]:
    rect(x,216,w,34);text(x+12,238,label,13,'#98a2b3')
button(1240,216,'查询',True,w=150)
table(252,277,1144,['提交时间','对象','操作','来源 / 操作者','任务','操作'],[
    ['今天 10:24','张三','主部门变更','飞书同步','#1040','查看差异'],['今天 09:40','人民路店','修改备注','管理员 陈琳','—','查看差异'],['昨天 16:08','滨江店','设置门店','管理员 陈琳','—','查看差异'],['昨天 14:02','钱某','确认离职','飞书同步','#1035','查看差异']], [180,190,170,220,190,194])
rect(236,646,1176,198);text(260,681,'差异预览 · 张三 / 主部门变更',16,weight=600)
text(260,721,'修改前',12,'#8b96a7');text(355,721,'大学城店');text(788,721,'修改后',12,'#8b96a7');text(883,721,'人民路店 / 后厨组',14,'#1677ff')
text(260,760,'主门店',12,'#8b96a7');text(355,760,'大学城店  →  人民路店');text(260,809,'显示系统发现与提交时间，不将其解释为真实调岗生效时间。',12,'#98a2b3')
save('05-audit.svg')

base('管理设置','配置连接、管理员资格、只读 API 客户端和每日核对。',4)
rect(236,192,1176,654)
for x,label in [(260,'飞书连接'),(404,'管理员白名单'),(592,'API 客户端'),(758,'每日核对')]:text(x,232,label,15,'#1677ff' if x==592 else '#667085',600 if x==592 else 400)
line(252,254,1396,254);parts.append('<path d="M584 254 L686 254" stroke="#1677ff" stroke-width="3"/>')
note(260,278,1128,'每个业务系统使用独立只读凭据','凭据仅允许读取 /api/v1；已有密钥不回显，新建或轮换后仅展示一次。')
text(260,385,'只读 API 客户端',18,weight=600);button(1196,360,'创建客户端',True,w=190)
table(252,412,1144,['使用方','凭据显示','状态','最近调用','操作'],[
    ['资产管理系统','仅显示凭据标识 · cli_asset','启用','今天 10:18','轮换 / 撤销'],['薪资核对服务','仅显示凭据标识 · cli_payroll','启用','昨天 18:40','轮换 / 撤销']], [220,355,150,190,229])
text(260,640,'访问边界',16,weight=600)
text(260,681,'管理端：飞书登录 + 管理员白名单；移出白名单或确认离职后撤销会话。',14,'#667085')
text(260,720,'飞书连接：展示应用与权限摘要；应用密钥仅录入或轮换。',14,'#667085')
text(260,759,'每日核对：默认北京时间 03:00；重叠任务合并或排队。',14,'#667085')
text(260,806,'凭据轮换和撤销需要确认；密钥不会进入日志或已有配置响应。',12,'#98a2b3')
save('06-settings.svg')

names=[('01-organization.svg','01 / 组织架构'),('02-employee.svg','02 / 人员详情'),('03-stores.svg','03 / 门店管理'),('04-sync.svg','04 / 同步中心'),('05-audit.svg','05 / 变更日志'),('06-settings.svg','06 / 管理设置')]
html='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>组织服务 · UI 原型</title><style>*{box-sizing:border-box}body{margin:0;background:#eef1f6;font:14px "Microsoft YaHei",sans-serif;color:#172b4d}header{padding:24px 4%;background:#fff;border-bottom:1px solid #dde3eb}h1{font-size:24px;margin:0 0 8px}p{color:#7b8798}nav{display:flex;gap:18px;flex-wrap:wrap}a{color:#1677ff;text-decoration:none}main{padding:20px 3%}section{scroll-margin:20px;margin-bottom:40px}img{display:block;width:100%;height:auto;border:1px solid #dde3eb;border-radius:8px}h2{font-size:17px}</style><header><h1>组织服务 / UI 原型评审</h1><p>Python + React / Ant Design 设计方向 · 六张静态原型 · 数据均为示例，图中按钮不执行操作</p><nav>'''
html+=''.join(f'<a href="#page{i}">{label}</a>' for i,(_,label) in enumerate(names))+'</nav></header><main>'
html+=''.join(f'<section id="page{i}"><h2>{label}</h2><a href="{name}" target="_blank"><img src="{name}" alt="{label}原型图"></a></section>' for i,(name,label) in enumerate(names))+'</main></html>'
(OUT/'index.html').write_text(html,encoding='utf-8')
print('已生成 6 张 SVG 原型与 HTML 总览。')
