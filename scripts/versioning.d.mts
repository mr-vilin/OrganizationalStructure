export const repositoryRoot: string;
export interface BuildInfo {
  version: string;
  commit: string;
  dirty: boolean | null;
  builtAt: string;
  stage: 'development' | 'prerelease' | 'release';
  releaseDate: string | null;
}
export function buildInfo(root?: string): BuildInfo;
