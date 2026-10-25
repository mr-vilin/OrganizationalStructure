import { BranchesOutlined, CheckCircleOutlined, CodeOutlined, DatabaseOutlined, FileTextOutlined, GithubOutlined, HistoryOutlined, LockOutlined, RocketOutlined } from '@ant-design/icons';
import { Alert, Card, Col, Descriptions, Divider, Row, Space, Tag, Timeline, Typography } from 'antd';
import { PageHeader } from '../components/PageHeader';
import { buildInfo, type BuildInfo } from '../buildInfo';
import { useResource } from '../services/useResource';

const productVersion = `v${buildInfo.version}`;
const releaseDate = buildInfo.releaseDate ?? '尚未发布';
const stage = buildInfo.stage === 'development' ? '开发构建，尚未发布' : buildInfo.stage === 'prerelease' ? '预发布版本' : '已发行版本';
const versionStatus = buildInfo.version.startsWith('0.') ? `开发初始阶段（0.x）；${stage}` : stage;
const changelogUrl = 'https://github.com/mr-vilin/OrganizationalStructure/blob/main/CHANGELOG.md';

const architecture = [
  { title: '业务架构', items: ['组织架构：飞书部门、人员和关系', '门店管理：门店标记、编码、备注和归属', '同步中心：全量/局部同步、任务与失败重试', '变更日志：来源、操作者、差异和提交时间'] },
  { title: '技术架构', items: ['Ant Design Pro 6 + Umi Max 管理端', 'FastAPI + SQLAlchemy 服务端', 'MySQL 8.4 数据存储', 'Docker Compose + FastAPI 同源页面与 API'] },
];

const featureGroups = [
  { title: '系统与安全', items: ['飞书 OAuth 2.0 登录', '管理员白名单与逐接口鉴权', '配置式菜单与路由', 'CSRF 请求保护', '独立 API 凭据', 'HTTPS 与会话安全'] },
  { title: '组织与门店', items: ['组织树与人员详情', '门店标记、编码和备注', '最近门店与主门店派生', '批量预览与版本冲突保护', '失效记录与变更日志'] },
  { title: '同步与开放能力', items: ['全量与局部同步', '每日全量核对', '失败事件重试', '只读 API 分页与一致版本', '数据世代与恢复核对'] },
];

const releaseTimeline = [
  { version: productVersion, date: releaseDate, label: '当前构建', description: '采用 SemVer 规范，开发阶段与已发行版本分别展示；旧编号保留在历史归档中。' },
];

export function SystemInfoPage() {
  const backend = useResource<BuildInfo>('/admin/api/system/version');
  const mismatch = backend.data && (backend.data.version !== buildInfo.version ||
    (backend.data.commit !== 'unknown' && buildInfo.commit !== 'unknown' && backend.data.commit !== buildInfo.commit) ||
    backend.data.stage !== buildInfo.stage ||
    (backend.data.dirty !== null && buildInfo.dirty !== null && backend.data.dirty !== buildInfo.dirty));
  return <PageHeader title="系统信息" description="查看当前产品版本、系统能力、技术栈和版本演进规则。" extra={<Tag color="blue">产品版本 {productVersion}</Tag>}>
    <Alert className="block-gap" type="info" showIcon title="版本记录规则" description="遵循 SemVer：新功能增加次版本，修复增加修订版本；0.x 阶段的破坏性变化增加次版本。开发改动先记入 Unreleased，发布时按版本整理记录，允许同日多个版本。" />
    {mismatch && <Alert className="block-gap" type="warning" showIcon title="前后端构建不一致" description="请刷新页面；若提示持续存在，请检查前后端是否来自同一次部署。" />}
    {backend.error && <Alert className="block-gap" type="warning" showIcon title="后端运行版本尚未确认" description={backend.error.message} />}
    <Row gutter={[16, 16]} className="block-gap">
      <Col xs={24} lg={14}><Card title={<Space><RocketOutlined />当前版本</Space>} extra={<Tag color="blue">{buildInfo.stage === 'development' ? '开发版本' : '发行版本'}</Tag>}><Descriptions column={{ xs: 1, sm: 2 }} items={[
        { key: 'product', label: '产品版本', children: <Typography.Title level={2} style={{ margin: 0 }}>{productVersion}</Typography.Title> },
        { key: 'date', label: '发布日期', children: releaseDate },
        { key: 'status', label: '发布状态', children: versionStatus },
        { key: 'backend', label: '后端运行版本', children: backend.data ? `v${backend.data.version}` : backend.error ? '读取失败，未确认' : '读取中' },
        { key: 'commit', label: '前端提交', children: buildInfo.commit === 'unknown' ? '未知' : buildInfo.commit.slice(0, 12) },
        { key: 'backend-commit', label: '后端提交', children: !backend.data || backend.data.commit === 'unknown' ? '未知' : backend.data.commit.slice(0, 12) },
        { key: 'built', label: '前端构建时间', children: buildInfo.builtAt ? new Date(buildInfo.builtAt).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '未知' },
        { key: 'dirty', label: '前端源码状态', children: buildInfo.dirty === null ? '未知' : buildInfo.dirty ? '包含未提交改动' : '干净提交' },
        { key: 'source', label: '版本来源', children: 'version.json（构建时注入）' },
      ]} /></Card></Col>
      <Col xs={24} lg={10}><Card title={<Space><CodeOutlined />版本分层</Space>}><Descriptions column={1} size="small" items={[{ key: 'frontend', label: '前端包版本', children: '0.1.0（frontend/package.json）' }, { key: 'backend', label: '后端包版本', children: '0.1.0（backend/pyproject.toml）' }, { key: 'api', label: 'API 契约版本', children: '1.0.0（FastAPI OpenAPI）' }, { key: 'data', label: '业务数据版本', children: '由 dataset_epoch + data_version 共同标识' }]} /></Card></Col>
    </Row>
    <Card className="block-gap" title={<Space><BranchesOutlined />系统架构</Space>}><Row gutter={[24, 24]}>{architecture.map((group) => <Col xs={24} md={12} key={group.title}><Typography.Title level={4}>{group.title}</Typography.Title><ul className="system-info-list">{group.items.map((item) => <li key={item}>{item}</li>)}</ul></Col>)}</Row></Card>
    <Card className="block-gap" title={<Space><CheckCircleOutlined />功能概览</Space>}><Row gutter={[24, 24]}>{featureGroups.map((group) => <Col xs={24} md={8} key={group.title}><Typography.Title level={4}>{group.title}</Typography.Title><ul className="system-info-list">{group.items.map((item) => <li key={item}>{item}</li>)}</ul></Col>)}</Row></Card>
    <Card className="block-gap" title={<Space><DatabaseOutlined />技术栈与部署</Space>}><Row gutter={[24, 24]}><Col xs={24} md={12}><Descriptions column={1} size="small" items={[{ key: 'frontend', label: '前端', children: 'Ant Design Pro 6 · Umi Max 4.7 · React 19.3 · TypeScript 5.9 · Ant Design 6.6' }, { key: 'backend', label: '后端', children: 'Python 3.13 · FastAPI 0.116 · SQLAlchemy 2.0' }, { key: 'storage', label: '存储', children: 'MySQL 8.4 · InnoDB · utf8mb4' }]} /></Col><Col xs={24} md={12}><Descriptions column={1} size="small" items={[{ key: 'auth', label: '认证', children: '飞书 OAuth 2.0 · 安全会话 Cookie · CSRF · 管理员白名单' }, { key: 'deploy', label: '部署', children: 'Docker 多阶段构建 · Docker Compose · FastAPI 同源静态服务 · HTTPS 入口' }, { key: 'consistency', label: '一致性', children: '数据世代、全局内容版本、分页游标和 409 冲突重读' }]} /></Col></Row></Card>
    <Card className="block-gap" title={<Space><HistoryOutlined />版本演进</Space>}><Timeline items={releaseTimeline.map((item) => ({ color: 'blue', icon: <RocketOutlined />, content: <><Space><Typography.Text strong>{item.version}</Typography.Text><Tag>{item.date}</Tag><Tag color="blue">{item.label}</Tag></Space><Typography.Paragraph type="secondary" style={{ marginTop: 8 }}>{item.description}</Typography.Paragraph></> }))} /><Divider /><Typography.Paragraph><FileTextOutlined /> 版本升级信息保存位置：仓库根目录 <Typography.Text code>CHANGELOG.md</Typography.Text>。未发布改动收集到 Unreleased，发行记录保留迁移、回滚、验证和关联提交/PR 信息；旧编号仅作历史归档。</Typography.Paragraph><Typography.Paragraph><LockOutlined /> 合并门槛：更新 Unreleased 或说明无产品行为变化，并通过版本校验。正式发布前完成兼容性评审，版本、记录和 Git tag 必须一致。</Typography.Paragraph><Typography.Link href={changelogUrl} target="_blank" rel="noreferrer"><GithubOutlined /> 查看 CHANGELOG.md</Typography.Link> · <Typography.Link href="https://github.com/mr-vilin/OrganizationalStructure/blob/main/docs/versioning.md" target="_blank" rel="noreferrer">查看版本规范</Typography.Link></Card>
  </PageHeader>;
}

export default SystemInfoPage;
