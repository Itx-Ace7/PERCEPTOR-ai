"use client";

import { useMemo } from "react";
import { Background, BackgroundVariant, Controls, Handle, MiniMap, Position, ReactFlow, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Bundle } from "@/lib/types";

function StageNode({ data }: NodeProps) {
  const stage = data as {
    title: string;
    blurb: string;
    index: string;
    group: string;
    status: string;
    preview: string[];
    cached: boolean;
    duration: string;
    accent: string;
  };
  const label = stage.status === "running" ? "live" : stage.cached ? "cached" : stage.status;
  return (
    <article className={`stage-card ${stage.status} ${stage.cached ? "cached" : ""}`}>
      <Handle type="target" position={Position.Left} className="port" />
      <div className="accent-bar" style={{ background: stage.accent }} />
      <header>
        <span className="idx mono">{stage.index}</span>
        <span className="group-name">{stage.group}</span>
        <span className="status-word mono">{label}</span>
        <span className="led" />
      </header>
      <h3>{stage.title}</h3>
      <p>{stage.blurb}</p>
      <ul>{stage.preview.map((line) => <li key={line} className="mono">{line}</li>)}</ul>
      <footer className="mono">{stage.cached ? "served from cache" : stage.duration}</footer>
      <Handle type="source" position={Position.Right} className="port" />
    </article>
  );
}

const nodeTypes = { stage: StageNode };

export function PipelineCanvas({ bundle }: { bundle: Bundle }) {
  const signature = bundle.pipeline.nodes
    .map((node) => {
      const state = bundle.nodes[node.id];
      return `${node.id}:${state?.status || ""}:${state?.cached ? 1 : 0}:${(state?.preview || []).join("|")}`;
    })
    .join(";");
  const groups = bundle.pipeline.groups || {};
  const nodes = useMemo(() => bundle.pipeline.nodes.map((node, index) => {
    const state = bundle.nodes[node.id];
    const accent = groups[node.group]?.accent || "#7af3d6";
    return {
      id: node.id,
      type: "stage",
      position: node.position,
      data: {
        title: node.title,
        blurb: node.blurb,
        group: groups[node.group]?.label || node.group,
        index: String(index + 1).padStart(2, "0"),
        status: state?.status || "pending",
        preview: state?.preview?.length ? state.preview : ["Waiting"],
        cached: Boolean(state?.cached),
        duration: state?.duration_ms ? `${state.duration_ms} ms` : state?.status === "completed" ? "done" : "—",
        accent,
      },
      draggable: true,
    };
  }), [signature]);
  const edges = useMemo(() => bundle.pipeline.nodes.flatMap((node) =>
    (node.depends_on || []).map((source) => ({
      id: `${source}-${node.id}`,
      source,
      target: node.id,
      type: "smoothstep",
      animated: bundle.nodes[node.id]?.status === "running" || bundle.nodes[source]?.status === "running",
      className: bundle.nodes[node.id]?.status === "running" || bundle.nodes[source]?.status === "running" ? "edge-live" : "edge-idle",
      style: { stroke: "rgba(122,243,214,0.72)", strokeWidth: 1.8 },
    })),
  ), [signature]);

  return (
    <div className="canvas-wrap">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.18 }}
        minZoom={0.3}
        proOptions={{ hideAttribution: true }}
        nodesConnectable={false}
      >
        <Background variant={BackgroundVariant.Dots} color="rgba(122,243,214,0.16)" gap={26} size={1.1} />
        <Controls showInteractive={false} />
        <MiniMap
          pannable
          zoomable
          maskColor="rgba(4, 8, 12, 0.72)"
          nodeStrokeWidth={2}
          nodeColor={(node) => {
            const status = String((node.data as { status?: string }).status || "");
            if (status === "running") return "#7af3d6";
            if (status === "failed") return "#ff6d8a";
            if (status === "completed") return "#9dffc3";
            return "#243038";
          }}
        />
      </ReactFlow>
      <div className="canvas-legend mono">
        <span><i className="run" /> live</span>
        <span><i className="done" /> done</span>
        <span><i className="cache" /> cached</span>
      </div>
    </div>
  );
}
