import { BranchesOutlined, CheckCircleOutlined, CodeOutlined, DatabaseOutlined, FileTextOutlined, GithubOutlined, HistoryOutlined, LockOutlined, RocketOutlined } from '@ant-design/icons';
import { Alert, Card, Col, Descriptions, Divider, Row, Space, Tag, Timeline, Typography } from 'antd';
import { PageHeader } from '../components/PageHeader';

const productVersion = 'v2.8.62';
const releaseDate = '2026-10-10';
const changelogUrl = 'https://github.com/mr-vilin/OrganizationalStructure/blob/main/CHANGELOG.md';

const architecture = [
  { title: '业务架构', items: ['组织架构：飞书部门、人员和关系', '门店管理：门店标记、编码、备注和归属', '同步中心：全量/局部同步、任务与失败重试', '变更日志：来源、操作者、差异和提交时间'] },
  { title: '技术架构', items: ['React + Ant Design 管理端', 'FastAPI + SQLAlchemy 服务端', 'MySQL 8.4 数据存储', 'Docker Compose + Nginx 部署入口'] },
];

const featureGroups = [
  { title: '系统与安全', items: ['飞书 OAuth 2.0 登录', 'RBAC 权限管理', '动态菜单路由', '管理员白名单', '独立 API 凭据', 'HTTPS 与会话安全'] },
  { title: '组织与门店', items: ['组织树与人员详情', '门店标记、编码和备注', '最近门店与主门店派生', '批量预览与版本冲突保护', '失效记录与变更日志'] },
  { title: '同步与开放能力', items: ['全量与局部同步', '每日全量核对', '失败事件重试', '只读 API 分页与一致版本', '数据世代与恢复核对'] },
];

const releaseTimeline = [
  { version: productVersion, date: releaseDate, label: '当前产品版本', description: '系统信息页、产品版本台账和合并前版本记录规则落地。' },
  { version: 'v1.0', date: '2026-09-15', label: '首版基线', description: '完成组织架构、门店管理、同步中心、变更日志和管理设置的首版交付。' },
];

export function SystemInfoPage() {
  return <>
    <PageHeader title="系统信息" description="查看当前产品版本、系统能力、技术栈和版本演进规则。" extra={<Tag color="blue">产品版本 {productVersion}</Tag>} />
    <Alert className="block-gap" type="info" showIcon title="版本记录规则" description="发布完成并验证通过后，由发布负责人先追加 CHANGELOG.md，再更新本页当前产品版本。合并到远端 main 或提交指向 main 的 PR 前，版本台账必须随同一提交完成。" />
    <Row gutter={[16, 16]} className="block-gap">
      <Col xs={24} lg={14}><Card title={<Space><RocketOutlined />当前版本</Space>} extra={<Tag color="blue">当前基线</Tag>}><Descriptions column={{ xs: 1, sm: 2 }} items={[{ key: 'product', label: '产品版本', children: <Typography.Title level={2} style={{ margin: 0 }}>{productVersion}</Typography.Title> }, { key: 'date', label: '发布日期', children: releaseDate }, { key: 'status', label: '发布状态', children: '已完成本地验证' }, { key: 'source', label: '版本来源', children: <Typography.Link href={changelogUrl} target="_blank" rel="noreferrer">CHANGELOG.md</Typography.Link> }]} /></Card></Col>
      <Col xs={24} lg={10}><Card title={<Space><CodeOutlined />版本分层</Space>}><Descriptions column={1} size="small" items={[{ key: 'frontend', label: '前端包版本', children: '0.1.0（frontend/package.json）' }, { key: 'backend', label: '后端包版本', children: '0.1.0（backend/pyproject.toml）' }, { key: 'api', label: 'API 契约版本', children: '1.0.0（FastAPI OpenAPI）' }, { key: 'data', label: '业务数据版本', children: '由 dataset_epoch + data_version 共同标识' }]} /></Card></Col>
    </Row>
    <Card className="block-gap" title={<Space><BranchesOutlined />系统架构</Space>}><Row gutter={[24, 24]}>{architecture.map((group) => <Col xs={24} md={12} key={group.title}><Typography.Title level={4}>{group.title}</Typography.Title><ul className="system-info-list">{group.items.map((item) => <li key={item}>{item}</li>)}</ul></Col>)}</Row></Card>
    <Card className="block-gap" title={<Space><CheckCircleOutlined />功能概览</Space>}><Row gutter={[24, 24]}>{featureGroups.map((group) => <Col xs={24} md={8} key={group.title}><Typography.Title level={4}>{group.title}</Typography.Title><ul className="system-info-list">{group.items.map((item) => <li key={item}>{item}</li>)}</ul></Col>)}</Row></Card>
    <Card className="block-gap" title={<Space><DatabaseOutlined />技术栈与部署</Space>}><Row gutter={[24, 24]}><Col xs={24} md={12}><Descriptions column={1} size="small" items={[{ key: 'frontend', label: '前端', children: 'React 19.3 · TypeScript 5.9 · Vite 8.3 · Ant Design 6.6' }, { key: 'backend', label: '后端', children: 'Python 3.13 · FastAPI 0.116 · SQLAlchemy 2.0' }, { key: 'storage', label: '存储', children: 'MySQL 8.4 · InnoDB · utf8mb4' }]} /></Col><Col xs={24} md={12}><Descriptions column={1} size="small" items={[{ key: 'auth', label: '认证', children: '飞书 OAuth 2.0 · JWT/会话 · 管理员白名单' }, { key: 'deploy', label: '部署', children: 'Docker · Docker Compose · Nginx · HTTPS' }, { key: 'consistency', label: '一致性', children: '数据世代、全局内容版本、分页游标和 409 冲突重读' }]} /></Col></Row></Card>
    <Card className="block-gap" title={<Space><HistoryOutlined />版本演进</Space>}><Timeline items={releaseTimeline.map((item) => ({ color: item.version === productVersion ? 'blue' : 'gray', icon: item.version === productVersion ? <RocketOutlined /> : <HistoryOutlined />, content: <><Space><Typography.Text strong>{item.version}</Typography.Text><Tag>{item.date}</Tag><Tag color={item.version === productVersion ? 'blue' : undefined}>{item.label}</Tag></Space><Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>{item.description}</Typography.Paragraph></> }))} /><Divider /><Typography.Paragraph><FileTextOutlined /> 版本升级信息保存位置：仓库根目录 <Typography.Text code>CHANGELOG.md</Typography.Text>。每次发布追加一条记录，保留迁移、回滚、验证和关联提交/PR 信息；本页面只展示当前版本和演进规则。</Typography.Paragraph><Typography.Paragraph><LockOutlined /> 合并门槛：代码或部署行为发生变化时，PR 必须更新版本台账；纯文档、测试或依赖维护也要明确写出“无产品版本变化”。</Typography.Paragraph><Typography.Link href={changelogUrl} target="_blank" rel="noreferrer"><GithubOutlined /> 查看 CHANGELOG.md</Typography.Link></Card>
  </>;
}
