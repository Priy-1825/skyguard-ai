import { NextResponse } from 'next/server';

// Force Next.js to never cache this live data route
export const dynamic = 'force-dynamic'; 

// Temporary in-memory store for the rolling data
let latestTelemetry: any = null;

// Receives data from your Python streamer.py
export async function POST(req: Request) {
  try {
    latestTelemetry = await req.json();
    return NextResponse.json({ status: 'received' }, { status: 200 });
  } catch (error) {
    return NextResponse.json({ error: 'Invalid payload' }, { status: 400 });
  }
}

// Serves data to your Next.js dashboard
export async function GET() {
  if (!latestTelemetry) {
    return NextResponse.json({ status: 'waiting for data' }, { status: 200 });
  }
  return NextResponse.json(latestTelemetry, { status: 200 });
}