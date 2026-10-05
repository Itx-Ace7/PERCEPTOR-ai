import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

const DROP_REQUEST = new Set(["host", "connection", "content-length", "transfer-encoding", "expect"]);
const DROP_RESPONSE = new Set(["content-encoding", "content-length", "transfer-encoding"]);

function upstreamBase(): string {
  return (process.env.API_UPSTREAM || "http://127.0.0.1:8787").replace(/\/$/, "");
}

async function proxy(request: NextRequest, path: string[]): Promise<Response> {
  const target = `${upstreamBase()}/api/${path.join("/")}${request.nextUrl.search}`;
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!DROP_REQUEST.has(key.toLowerCase())) headers.set(key, value);
  });
  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  try {
    const response = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      cache: "no-store",
      redirect: "manual",
      // Node requires duplex when the request body is a stream.
      duplex: "half",
    } as RequestInit);
    const out = new Headers();
    response.headers.forEach((value, key) => {
      if (!DROP_RESPONSE.has(key.toLowerCase())) out.set(key, value);
    });
    return new Response(response.body, { status: response.status, statusText: response.statusText, headers: out });
  } catch {
    return NextResponse.json({ detail: "The analysis service is not reachable." }, { status: 503 });
  }
}

type Context = { params: Promise<{ path: string[] }> };

async function handle(request: NextRequest, context: Context): Promise<Response> {
  const { path } = await context.params;
  return proxy(request, path ?? []);
}

export const GET = handle;
export const POST = handle;
export const PUT = handle;
export const PATCH = handle;
export const DELETE = handle;
