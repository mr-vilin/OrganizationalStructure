export interface BuildInfo {
  version: string;
  commit: string;
  dirty: boolean | null;
  builtAt: string | null;
  stage: 'development' | 'prerelease' | 'release';
  releaseDate: string | null;
}

declare const __BUILD_INFO__: BuildInfo;
export const buildInfo = __BUILD_INFO__;
