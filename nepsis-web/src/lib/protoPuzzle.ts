import { spawn } from "child_process";
import path from "path";

export const SUPPORTED_PACK_IDS = ["jailing_jingall", "utf8_clean", "terminal_bench"] as const;
const PACK_ID_SET = new Set(SUPPORTED_PACK_IDS);

const PYTHON_BIN = process.env.NEPSIS_PYTHON ?? "python3";
const PROJECT_ROOT = process.env.NEPSIS_PROJECT_ROOT ?? path.resolve(process.cwd(), "..");
const CLI_MODULE = process.env.NEPSIS_PROTO_PUZZLE_CLI ?? "nepsis_cgn.cli.proto_puzzle_cli";

export type ProtoPackId = (typeof SUPPORTED_PACK_IDS)[number];
export type ProtoState = Record<string, unknown>;
export type ProtoEvaluation = {
  packId: string;
  packName: string;
  state: ProtoState;
  distance: number;
  isValid: boolean;
  violations: { code: string; severity: string; message: string; metadata?: Record<string, unknown> | null }[];
  hints: string[];
};

type CliReport = {
  pack_id: string;
  pack_name: string;
  state: Record<string, unknown>;
  is_valid: boolean;
  distance: number;
  violations: { code: string; severity: string; message: string; metadata?: Record<string, unknown> | null }[];
  hints: string[];
};

function runProtoPuzzleCli(packId: ProtoPackId, state: ProtoState) {
  return new Promise<CliReport>((resolve, reject) => {
    const stateJson = JSON.stringify(state);
    const args = ["-m", CLI_MODULE, "--pack", packId, "--json", "--state-json", stateJson];

    const child = spawn(PYTHON_BIN, args, {
      cwd: PROJECT_ROOT,
      env: process.env,
    });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });

    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });

    child.on("error", (error) => reject(error));

    child.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(`Proto puzzle CLI failed with code ${code}: ${stderr}`));
        return;
      }

      try {
        const payload = JSON.parse(stdout.trim()) as CliReport;
        resolve(payload);
      } catch (error) {
        reject(new Error(`Failed to parse CLI output: ${(error as Error).message}. Raw output: ${stdout}`));
      }
    });
  });
}

export function isSupportedProtoPack(value: string): value is ProtoPackId {
  return PACK_ID_SET.has(value as ProtoPackId);
}

export async function evaluateProtoPuzzleTs(packId: string, state: ProtoState): Promise<ProtoEvaluation> {
  if (!isSupportedProtoPack(packId)) {
    throw new Error(`Unknown packId ${packId}`);
  }

  const report = await runProtoPuzzleCli(packId, state);

  return {
    packId: report.pack_id,
    packName: report.pack_name,
    state: report.state,
    distance: report.distance,
    isValid: report.is_valid,
    violations: report.violations,
    hints: report.hints,
  };
}
