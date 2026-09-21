#!/usr/bin/env node
// Copyright 2026 Arkapravo Ghosh
// Official MCP runner bridge for Ark Browser.
// Communicates with official Model Context Protocol servers over stdio:
//   - @modelcontextprotocol/server-memory
//   - @modelcontextprotocol/server-sequential-thinking
//   - Custom stdio MCP servers

const fs = require('fs');
const path = require('path');

// Resolve node_modules from potential locations:
// 1. App bundle Resources: .../Contents/Resources/mcp/runtime/node_modules
// 2. App bundle Resources: .../Contents/Resources/mcp/node_modules
// 3. Repo third_party: .../third_party/mcp/node_modules
// 4. Local node_modules relative to this runner script
const candidateModulePaths = [
  path.join(__dirname, 'runtime', 'node_modules'),
  path.join(__dirname, 'node_modules'),
  path.join(__dirname, '..', 'third_party', 'mcp', 'node_modules'),
  path.join(__dirname, '..', 'node_modules'),
];

for (const p of candidateModulePaths) {
  if (fs.existsSync(p)) {
    module.paths.unshift(p);
  }
}

let Client, StdioClientTransport, StreamableHTTPClientTransport, SSEClientTransport;
try {
  Client = require('@modelcontextprotocol/sdk/client/index.js').Client;
  StdioClientTransport = require('@modelcontextprotocol/sdk/client/stdio.js').StdioClientTransport;
  try {
    StreamableHTTPClientTransport = require('@modelcontextprotocol/sdk/client/streamableHttp.js').StreamableHTTPClientTransport;
  } catch {}
  try {
    SSEClientTransport = require('@modelcontextprotocol/sdk/client/sse.js').SSEClientTransport;
  } catch {}
} catch (e) {
  console.error(JSON.stringify({
    success: false,
    error: 'Failed to load @modelcontextprotocol/sdk: ' + e.message,
  }));
  process.exit(1);
}

// Helper to resolve server script paths
function resolveServerScript(serverNameOrPath) {
  const norm = (serverNameOrPath || '').toLowerCase();
  if (norm === 'ark.memory' || norm === 'memory' || norm === 'server-memory') {
    try {
      return require.resolve('@modelcontextprotocol/server-memory/dist/index.js');
    } catch {
      // Look in candidate paths directly
      for (const p of candidateModulePaths) {
        const direct = path.join(p, '@modelcontextprotocol', 'server-memory', 'dist', 'index.js');
        if (fs.existsSync(direct)) return direct;
      }
    }
  }
  if (norm === 'ark.sequential_thinking' || norm === 'sequential_thinking' ||
      norm === 'sequentialthinking' || norm === 'server-sequential-thinking') {
    try {
      return require.resolve('@modelcontextprotocol/server-sequential-thinking/dist/index.js');
    } catch {
      for (const p of candidateModulePaths) {
        const direct = path.join(p, '@modelcontextprotocol', 'server-sequential-thinking', 'dist', 'index.js');
        if (fs.existsSync(direct)) return direct;
      }
    }
  }

  // Check if it is a filesystem path
  if (fs.existsSync(serverNameOrPath)) {
    return path.resolve(serverNameOrPath);
  }

  throw new Error(`Cannot resolve MCP server script for "${serverNameOrPath}"`);
}

function getDefaultMemoryPath() {
  return path.join(require('os').homedir(), '.arkbrowser', 'mcp', 'memory.jsonl');
}

function ensureDirectoryForFile(filePath) {
  if (!filePath) return;
  try {
    const dir = path.dirname(filePath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
  } catch {}
}

// Connect to an MCP server via stdio transport
async function connectToServer(serverScriptOrCommand, options = {}) {
  const env = { ...process.env, ...(options.env || {}) };
  const memPath = options.memoryFilePath || getDefaultMemoryPath();
  env.MEMORY_FILE_PATH = memPath;
  ensureDirectoryForFile(memPath);

  let command = process.execPath;
  let args = [serverScriptOrCommand];

  if (options.command) {
    command = options.command;
    args = options.args || [];
  }

  const transport = new StdioClientTransport({
    command,
    args,
    env,
    stderr: 'ignore', // Do not pollute stdout JSON
  });

  const client = new Client(
    { name: 'ark-browser-client', version: '1.0.0' },
    { capabilities: {} }
  );

  await client.connect(transport);
  return { client, transport };
}

// Parse command line arguments
function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg.startsWith('--')) {
      const key = arg.slice(2);
      if (i + 1 < argv.length && !argv[i + 1].startsWith('--')) {
        args[key] = argv[++i];
      } else {
        args[key] = true;
      }
    } else {
      args._.push(arg);
    }
  }
  return args;
}

// Connect to a remote MCP server via HTTP/SSE transport
async function connectToHttpServer(urlStr, options = {}) {
  const url = new URL(urlStr);
  const client = new Client(
    { name: 'ark-browser-client', version: '1.0.0' },
    { capabilities: {} }
  );

  let transport;
  if (StreamableHTTPClientTransport) {
    try {
      transport = new StreamableHTTPClientTransport(url, options);
      await client.connect(transport);
      return { client, transport };
    } catch (streamErr) {
      if (SSEClientTransport) {
        try {
          transport = new SSEClientTransport(url, options);
          await client.connect(transport);
          return { client, transport };
        } catch (sseErr) {
          throw new Error(`Failed to connect to remote MCP server at ${urlStr}: ${streamErr.message} (SSE fallback: ${sseErr.message})`);
        }
      } else {
        throw streamErr;
      }
    }
  } else if (SSEClientTransport) {
    transport = new SSEClientTransport(url, options);
    await client.connect(transport);
    return { client, transport };
  } else {
    throw new Error('Neither StreamableHTTPClientTransport nor SSEClientTransport could be loaded.');
  }
}

// Connect to target server (either bundled script, custom command/args, or remote URL)
async function connectToTarget(parsed, options = {}) {
  const memoryFilePath = parsed['memory-file'] || parsed.memoryFilePath || getDefaultMemoryPath();
  ensureDirectoryForFile(memoryFilePath);

  const targetUrl = parsed.url ||
    (typeof parsed.command === 'string' && (parsed.command.startsWith('http://') || parsed.command.startsWith('https://')) ? parsed.command : null) ||
    (typeof parsed.server === 'string' && (parsed.server.startsWith('http://') || parsed.server.startsWith('https://')) ? parsed.server : null);

  if (targetUrl) {
    let extraEnv = {};
    if (parsed.env) {
      try {
        extraEnv = typeof parsed.env === 'string' ? JSON.parse(parsed.env) : parsed.env;
      } catch (e) {
        throw new Error(`Invalid JSON in --env: ${e.message}`);
      }
    }
    return await connectToHttpServer(targetUrl, { env: extraEnv, ...options });
  }

  if (parsed.command) {
    let cmdArgs = [];
    const rawArgs = parsed['cmd-args'] || parsed.cmd_args;
    if (rawArgs) {
      try {
        cmdArgs = typeof rawArgs === 'string' ? JSON.parse(rawArgs) : rawArgs;
      } catch (e) {
        throw new Error(`Invalid JSON in --cmd-args: ${e.message}`);
      }
    }
    let extraEnv = {};
    if (parsed.env) {
      try {
        extraEnv = typeof parsed.env === 'string' ? JSON.parse(parsed.env) : parsed.env;
      } catch (e) {
        throw new Error(`Invalid JSON in --env: ${e.message}`);
      }
    }
    return await connectToServer(null, {
      command: parsed.command,
      args: cmdArgs,
      env: extraEnv,
      memoryFilePath,
      ...options,
    });
  }

  const server = parsed.server || 'sequential_thinking';
  const script = resolveServerScript(server);
  return await connectToServer(script, { memoryFilePath, ...options });
}

// Execute a tool call on an MCP server
async function handleCallTool(parsed) {
  const toolName = parsed.tool || parsed.name;
  let toolArgs = {};
  if (parsed.args) {
    try {
      toolArgs = typeof parsed.args === 'string' ? JSON.parse(parsed.args) : parsed.args;
    } catch (e) {
      throw new Error(`Invalid JSON in --args: ${e.message}`);
    }
  }

  const { client, transport } = await connectToTarget(parsed);

  try {
    // Map tool alias if needed (e.g. sequential_thinking -> sequentialthinking)
    let actualTool = toolName;
    if (toolName === 'sequential_thinking') {
      actualTool = 'sequentialthinking';
    }

    // Argument normalization for official memory server
    if (actualTool === 'add_observations') {
      const entityName = toolArgs.entityName || toolArgs.entity_name || toolArgs.name;
      const rawObs = toolArgs.contents || toolArgs.observations;
      if (entityName && rawObs) {
        const obsList = Array.isArray(rawObs) ? rawObs : [rawObs];
        // Check if entity exists
        const graph = await client.callTool({ name: 'read_graph', arguments: {} });
        let exists = false;
        if (graph && !graph.isError) {
          if (graph.structuredContent && Array.isArray(graph.structuredContent.entities)) {
            exists = graph.structuredContent.entities.some(e => e.name === entityName);
          } else if (Array.isArray(graph.content) && graph.content[0]?.text) {
            try {
              const p = JSON.parse(graph.content[0].text);
              exists = (p.entities || []).some(e => e.name === entityName);
            } catch {}
          }
        }
        if (!exists) {
          actualTool = 'create_entities';
          toolArgs = {
            entities: [{
              name: entityName,
              entityType: 'user',
              observations: obsList,
            }],
          };
        } else {
          toolArgs = {
            observations: [{
              entityName,
              contents: obsList,
            }],
          };
        }
      }
    } else if (actualTool === 'create_entities') {
      const singleName = toolArgs.name || toolArgs.entityName || toolArgs.entity_name;
      const singleObs = toolArgs.observations || toolArgs.contents;
      if (singleName && singleObs) {
        toolArgs = {
          entities: [{
            name: singleName,
            entityType: toolArgs.entityType || 'user',
            observations: Array.isArray(singleObs) ? singleObs : [singleObs],
          }],
        };
      }
    } else if (actualTool === 'delete_entities') {
      const name = toolArgs.entity_name || toolArgs.entityName || toolArgs.name;
      if (name && !toolArgs.entityNames) {
        toolArgs = { entityNames: [name] };
      }
    } else if (actualTool === 'sequentialthinking') {
      if (toolArgs.thoughtNumber) toolArgs.thoughtNumber = parseInt(toolArgs.thoughtNumber, 10);
      if (toolArgs.totalThoughts) toolArgs.totalThoughts = parseInt(toolArgs.totalThoughts, 10);
      if (typeof toolArgs.nextThoughtNeeded === 'string') {
        toolArgs.nextThoughtNeeded = toolArgs.nextThoughtNeeded.toLowerCase() === 'true';
      }
    }

    const result = await client.callTool({
      name: actualTool,
      arguments: toolArgs,
    });

    if (result && result.isError) {
      const errMsg = result.content?.[0]?.text || 'Tool returned error';
      return { success: false, error: errMsg, result };
    }

    return { success: true, result };
  } finally {
    try { await client.close(); } catch {}
  }
}

// List available tools from an MCP server
async function handleListTools(parsed) {
  const { client, transport } = await connectToTarget(parsed);

  try {
    const list = await client.listTools();
    return { success: true, tools: list.tools || [] };
  } finally {
    try { await client.close(); } catch {}
  }
}

// Migrate legacy memory.json if memory.jsonl is missing or empty
async function checkAndMigrateLegacyMemory(client, memoryFilePath) {
  if (!memoryFilePath) return;
  const legacyPath = path.join(path.dirname(memoryFilePath), 'memory.json');
  const legacyDataPath = path.join(path.dirname(path.dirname(memoryFilePath)), 'data', 'memory.json');
  const candidates = [legacyPath, legacyDataPath];

  let sourcePath = null;
  for (const c of candidates) {
    if (fs.existsSync(c)) {
      sourcePath = c;
      break;
    }
  }
  if (!sourcePath) return;

  const jsonlExists = fs.existsSync(memoryFilePath) && fs.statSync(memoryFilePath).size > 0;
  if (jsonlExists) return;

  try {
    const raw = fs.readFileSync(sourcePath, 'utf8');
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.length > 0) {
      const entities = parsed.map(item => ({
        name: item.entity_name || item.name || 'Entity',
        entityType: 'user',
        observations: item.observations || [],
      }));
      await client.callTool({
        name: 'create_entities',
        arguments: { entities },
      });
    }
  } catch (err) {
    // Ignore migration failure and proceed
  }
}

// Handle dedicated Memory Knowledge Graph operations
async function handleMemoryOp(parsed) {
  const action = parsed.action;
  const memoryFilePath = parsed['memory-file'] || parsed.memoryFilePath || getDefaultMemoryPath();
  ensureDirectoryForFile(memoryFilePath);
  const script = resolveServerScript('memory');
  const { client, transport } = await connectToServer(script, { memoryFilePath });

  try {
    await checkAndMigrateLegacyMemory(client, memoryFilePath);

    if (action === 'get-entries') {
      const graphRes = await client.callTool({ name: 'read_graph', arguments: {} });
      if (graphRes && graphRes.isError) {
        throw new Error(graphRes.content?.[0]?.text || 'Failed to read memory graph');
      }
      let entities = [];
      if (graphRes && graphRes.structuredContent && Array.isArray(graphRes.structuredContent.entities)) {
        entities = graphRes.structuredContent.entities;
      } else if (graphRes && Array.isArray(graphRes.content) && graphRes.content[0]?.text) {
        try {
          const parsedGraph = JSON.parse(graphRes.content[0].text);
          if (Array.isArray(parsedGraph.entities)) {
            entities = parsedGraph.entities;
          }
        } catch {}
      }

      const entries = entities.map(e => ({
        entity_name: e.name,
        observations: e.observations || [],
      }));
      return { success: true, entries };
    }

    if (action === 'save-entry') {
      const entityName = parsed.entity || parsed.name;
      if (!entityName) throw new Error('Missing --entity');
      let observations = [];
      if (parsed.observations) {
        try {
          observations = typeof parsed.observations === 'string'
            ? JSON.parse(parsed.observations)
            : parsed.observations;
        } catch {
          observations = [String(parsed.observations)];
        }
      }

      // Check if entity already exists
      const graphRes = await client.callTool({ name: 'read_graph', arguments: {} });
      if (graphRes && graphRes.isError) {
        throw new Error(graphRes.content?.[0]?.text || 'Failed to read memory graph');
      }
      let exists = false;
      let existingEntities = [];
      if (graphRes && graphRes.structuredContent && Array.isArray(graphRes.structuredContent.entities)) {
        existingEntities = graphRes.structuredContent.entities;
      } else if (graphRes && Array.isArray(graphRes.content) && graphRes.content[0]?.text) {
        try {
          const parsedGraph = JSON.parse(graphRes.content[0].text);
          existingEntities = parsedGraph.entities || [];
        } catch {}
      }

      exists = existingEntities.some(e => e.name === entityName);

      let opRes;
      if (exists) {
        // Add observations to existing entity
        opRes = await client.callTool({
          name: 'add_observations',
          arguments: {
            observations: [{
              entityName,
              contents: observations,
            }],
          },
        });
      } else {
        // Create new entity
        opRes = await client.callTool({
          name: 'create_entities',
          arguments: {
            entities: [{
              name: entityName,
              entityType: 'user',
              observations,
            }],
          },
        });
      }
      if (opRes && opRes.isError) {
        throw new Error(opRes.content?.[0]?.text || 'Failed to save entity to memory');
      }
      return { success: true };
    }

    if (action === 'delete-entry') {
      const entityName = parsed.entity || parsed.name;
      if (!entityName) throw new Error('Missing --entity');
      const delRes = await client.callTool({
        name: 'delete_entities',
        arguments: { entityNames: [entityName] },
      });
      if (delRes && delRes.isError) {
        throw new Error(delRes.content?.[0]?.text || 'Failed to delete entity from memory');
      }
      return { success: true };
    }

    if (action === 'clear-all') {
      const graphRes = await client.callTool({ name: 'read_graph', arguments: {} });
      let entityNames = [];
      if (graphRes && !graphRes.isError) {
        if (graphRes.structuredContent && Array.isArray(graphRes.structuredContent.entities)) {
          entityNames = graphRes.structuredContent.entities.map(e => e.name);
        } else if (Array.isArray(graphRes.content) && graphRes.content[0]?.text) {
          try {
            const parsedGraph = JSON.parse(graphRes.content[0].text);
            entityNames = (parsedGraph.entities || []).map(e => e.name);
          } catch {}
        }
      }

      if (entityNames.length > 0) {
        const delRes = await client.callTool({
          name: 'delete_entities',
          arguments: { entityNames },
        });
        if (delRes && delRes.isError) {
          throw new Error(delRes.content?.[0]?.text || 'Failed to delete entities from memory');
        }
      }
      // Also truncate file if present
      if (memoryFilePath && fs.existsSync(memoryFilePath)) {
        try { fs.writeFileSync(memoryFilePath, ''); } catch {}
      }
      return { success: true };
    }

    if (action === 'get-summary') {
      const graphRes = await client.callTool({ name: 'read_graph', arguments: {} });
      if (graphRes && graphRes.isError) {
        return { success: true, summary: '' };
      }
      let entities = [];
      if (graphRes && graphRes.structuredContent && Array.isArray(graphRes.structuredContent.entities)) {
        entities = graphRes.structuredContent.entities;
      } else if (graphRes && Array.isArray(graphRes.content) && graphRes.content[0]?.text) {
        try {
          const parsedGraph = JSON.parse(graphRes.content[0].text);
          entities = parsedGraph.entities || [];
        } catch {}
      }

      if (!entities.length) {
        return { success: true, summary: '' };
      }

      const lines = ['Stored memories about user and context:'];
      for (const e of entities) {
        const obs = (e.observations || []).join('; ');
        lines.push(`- ${e.name}: ${obs}`);
      }
      return { success: true, summary: lines.join('\n') };
    }

    throw new Error(`Unknown memory action "${action}"`);
  } finally {
    try { await client.close(); } catch {}
  }
}

// Self-test command to verify servers operate correctly
async function handleTest(parsed) {
  const tmpMemory = path.join(require('os').tmpdir(), 'ark_mcp_test_' + Date.now() + '.jsonl');
  try {
    // 1. Test Sequential Thinking
    const seqRes = await handleCallTool({
      server: 'sequential_thinking',
      tool: 'sequentialthinking',
      args: {
        thought: 'Testing MCP execution',
        thoughtNumber: 1,
        totalThoughts: 1,
        nextThoughtNeeded: false,
      },
    });

    // 2. Test Memory Knowledge Graph
    const memSave = await handleMemoryOp({
      action: 'save-entry',
      entity: 'TestUser',
      observations: JSON.stringify(['Favorite language: Rust']),
      'memory-file': tmpMemory,
    });

    const memGet = await handleMemoryOp({
      action: 'get-entries',
      'memory-file': tmpMemory,
    });

    const memSummary = await handleMemoryOp({
      action: 'get-summary',
      'memory-file': tmpMemory,
    });

    return {
      success: true,
      sequential_thinking: seqRes.success,
      memory_save: memSave.success,
      memory_entries_count: (memGet.entries || []).length,
      memory_summary: memSummary.summary,
    };
  } finally {
    try { if (fs.existsSync(tmpMemory)) fs.unlinkSync(tmpMemory); } catch {}
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const command = args._[0];

  let output;
  try {
    if (command === 'call-tool') {
      output = await handleCallTool(args);
    } else if (command === 'list-tools') {
      output = await handleListTools(args);
    } else if (command === 'memory-op') {
      output = await handleMemoryOp(args);
    } else if (command === 'test') {
      output = await handleTest(args);
    } else {
      throw new Error(`Unknown command "${command}". Valid commands: call-tool, list-tools, memory-op, test`);
    }
  } catch (err) {
    output = { success: false, error: err.message || String(err) };
  }

  console.log(JSON.stringify(output));
}

main().catch(err => {
  console.log(JSON.stringify({ success: false, error: err.message }));
  process.exit(1);
});
