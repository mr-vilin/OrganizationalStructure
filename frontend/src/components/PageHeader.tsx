import type { ReactNode } from 'react';
export function PageHeader({ title, description, extra }: { title: string; description: string; extra?: ReactNode }) { return <header className="page-header"><div><div className="breadcrumb">工作台 / {title}</div><h1>{title}</h1><p>{description}</p></div>{extra}</header>; }
