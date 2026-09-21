#!/usr/bin/env node
const fs = require('fs');
const path = require('path');

const candidateModulePaths = [
  path.join(__dirname, '..', 'third_party', 'mcp', 'node_modules'),
  path.join(__dirname, '..', 'chromium', 'src', 'out', 'ArkDev', 'Ark Browser.app', 'Contents', 'Resources', 'mcp', 'runtime', 'node_modules'),
];
for (const p of candidateModulePaths) {
  if (fs.existsSync(p)) {
    module.paths.unshift(p);
  }
}

const { Server } = require('@modelcontextprotocol/sdk/server/index.js');
const { StdioServerTransport } = require('@modelcontextprotocol/sdk/server/stdio.js');
const { CallToolRequestSchema, ListToolsRequestSchema } = require('@modelcontextprotocol/sdk/types.js');

const server = new Server(
  { name: 'test-weather-mcp', version: '1.0.0' },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: 'search_location',
      description: 'Search for a location by city or place name to retrieve geographical coordinates (latitude and longitude).',
      inputSchema: {
        type: 'object',
        properties: {
          query: { type: 'string', description: 'City or place name to search (e.g. "Kolkata", "Paris", "Tokyo")' },
        },
        required: ['query'],
      },
    },
    {
      name: 'get_current_weather',
      description: 'Get real-time weather conditions for specific coordinates.',
      inputSchema: {
        type: 'object',
        properties: {
          latitude: { type: 'number', description: 'Latitude coordinate' },
          longitude: { type: 'number', description: 'Longitude coordinate' },
        },
        required: ['latitude', 'longitude'],
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  if (request.params.name === 'search_location') {
    const rawQuery = String(request.params.arguments?.query || '').trim();
    const qLower = rawQuery.toLowerCase();

    // If the input is conversational sentences (like the bug where the whole prompt was passed), fail exactly like OpenMeteo!
    if (qLower.includes('can you check') || qLower.includes('using weather mcp') || qLower.length > 35) {
      return {
        isError: true,
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              error: `OpenMeteo API Error: No locations found matching "${rawQuery}". Tried 3 provider(s): Census.gov: No results found; Nominatim: No results found; Open-Meteo: No results found`,
              suggestions: [
                'Add more detail (e.g., "Paris, France" instead of "Paris")',
                'Check spelling',
                'Use a nearby major city',
                'Try providing coordinates directly (latitude, longitude)',
              ],
            }),
          },
        ],
      };
    }

    if (qLower.includes('kolkata') || qLower.includes('calcutta')) {
      return {
        content: [
          {
            type: 'text',
            text: JSON.stringify([
              {
                id: 1275004,
                name: 'Kolkata',
                latitude: 22.5726,
                longitude: 88.3639,
                country: 'India',
                admin1: 'West Bengal',
                timezone: 'Asia/Kolkata',
              },
            ]),
          },
        ],
      };
    }

    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify([
            {
              id: 999999,
              name: rawQuery,
              latitude: 20.0,
              longitude: 77.0,
              country: 'India',
            },
          ]),
        },
      ],
    };
  }

  if (request.params.name === 'get_current_weather') {
    const lat = Number(request.params.arguments?.latitude ?? 22.5726);
    const lon = Number(request.params.arguments?.longitude ?? 88.3639);
    return {
      content: [
        {
          type: 'text',
          text: JSON.stringify({
            latitude: lat,
            longitude: lon,
            city: 'Kolkata',
            current_weather: {
              temperature_c: 29.2,
              weather_condition: 'Partly Cloudy',
              relative_humidity_pct: 74,
              wind_speed_kmh: 11.5,
              wind_direction: 'South-Southeast',
              uv_index: 6.2,
            },
          }),
        },
      ],
    };
  }

  throw new Error(`Tool not found: ${request.params.name}`);
});

async function run() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

run().catch((err) => {
  console.error('Weather MCP server error:', err);
  process.exit(1);
});
