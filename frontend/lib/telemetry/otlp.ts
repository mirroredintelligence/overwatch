// The telemetry batch as OTLP/JSON for the collector's logs receiver (O02). It lives here and
// not in the route file because a Next.js route module may export HTTP methods and route settings
// only (the build refuses any other export).

export type Attribute = string | number | boolean;
export type TelemetryEvent = { name: string; at: number; attributes: Record<string, Attribute> };

// The batch goes to the collector's OTLP logs receiver as OTLP/JSON. ui.* events are log records
// (DEC-331 item 5 keeps them in the logs pipeline), and the collector's receivers accept OTLP only
// (known issue O04). Each event becomes one log record: its name is the body, and its allow-listed
// attributes, plus the event name, are the attributes.
export const OTLP_LOGS_PATH = '/v1/logs';
const NANOSECONDS_PER_MILLISECOND = BigInt(1_000_000);

type OtlpValue = { stringValue: string } | { doubleValue: number } | { boolValue: boolean };

function otlpValue(value: Attribute): OtlpValue {
  if (typeof value === 'number') return { doubleValue: value };
  if (typeof value === 'boolean') return { boolValue: value };
  return { stringValue: value };
}

/** The batch as one OTLP/JSON request to the logs receiver. */
export function otlpLogs(events: TelemetryEvent[]): unknown {
  return {
    resourceLogs: [
      {
        resource: { attributes: [{ key: 'service.name', value: { stringValue: 'diucs-browser' } }] },
        scopeLogs: [
          {
            scope: { name: 'diucs.ui' },
            logRecords: events.map((event) => {
              const time = (BigInt(Math.round(event.at)) * NANOSECONDS_PER_MILLISECOND).toString();
              return {
                timeUnixNano: time,
                observedTimeUnixNano: time,
                body: { stringValue: event.name },
                attributes: [
                  { key: 'event.name', value: { stringValue: event.name } },
                  ...Object.entries(event.attributes).map(([key, value]) => ({ key, value: otlpValue(value) })),
                ],
              };
            }),
          },
        ],
      },
    ],
  };
}

