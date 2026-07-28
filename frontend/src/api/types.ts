export type NodeSourceType = 'xui' | (string & {});

export type NodeFlag = number | boolean;

export interface NodeRecord {
  id: number;
  name: string;
  panel_url: string;
  source_type: NodeSourceType;
  verify_tls: NodeFlag;
  enabled: NodeFlag;
  read_only: NodeFlag;
  api_version: string;
  ip?: string;
  port?: string;
  url?: string;
  scheme?: string;
  base_path?: string;
  panel_version?: string;
  user?: string;
  password?: string;
  bearer_token?: string;
  tags?: string[];
}
