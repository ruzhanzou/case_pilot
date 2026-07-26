"use client";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { BrainCircuit, Check, ChevronDown } from "lucide-react";

export const modelOptions = [
  {
    id: "auto",
    label: "自动选择",
    description: "根据任务复杂度智能选择模型",
  },
  {
    id: "pro",
    label: "Test Design Pro",
    description: "适合复杂需求与风险分析",
  },
  {
    id: "local",
    label: "本地模型",
    description: "优先使用本地推理服务",
  },
] as const;

export type ModelId = (typeof modelOptions)[number]["id"];

export function ModelSelector({
  value,
  onValueChange,
  placement = "global",
}: {
  value: ModelId;
  onValueChange: (value: ModelId) => void;
  placement?: "global" | "studio";
}) {
  const selectedModel =
    modelOptions.find((model) => model.id === value) ?? modelOptions[0];

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          aria-label={`选择模型，当前为${selectedModel.label}`}
          className={`model-selector model-selector--${placement}`}
          type="button"
        >
          <BrainCircuit size={15} />
          <span>{selectedModel.label}</span>
          <ChevronDown size={13} />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        className="model-selector-menu"
        sideOffset={8}
      >
        {modelOptions.map((model) => (
          <DropdownMenuItem
            className="model-selector-option"
            key={model.id}
            onSelect={() => onValueChange(model.id)}
          >
            <span>
              <strong>{model.label}</strong>
              <small>{model.description}</small>
            </span>
            {value === model.id ? <Check size={16} /> : null}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
