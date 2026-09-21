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
  { name: 'test-custom-mcp', version: '1.0.0' },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: 'calculate_magic_multiplier',
      description: 'Calculates the special magic multiplier between two numbers',
      inputSchema: {
        type: 'object',
        properties: {
          a: { type: 'number', description: 'First number' },
          b: { type: 'number', description: 'Second number' },
        },
        required: ['a', 'b'],
      },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  if (request.params.name === 'calculate_magic_multiplier') {
    const a = Number(request.params.arguments?.a ?? 6);
    const b = Number(request.params.arguments?.b ?? 7);
    return {
      content: [
        {
          type: 'text',
          text: `Calculation successful: ${a} * ${b} = ${a * b}. Magic code is MAGIC-${a * b}.`,
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
  console.error('Fatal error in test custom MCP server:', err);
  process.exit(1);
});
