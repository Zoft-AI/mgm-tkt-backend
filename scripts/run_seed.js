const { Client } = require("pg");
const fs = require("fs");
const path = require("path");

async function run() {
  const client = new Client({
    host: "localhost",
    port: 5433,
    database: "postgres",
    user: "postgres",
    password: "RARwxd962bT6yOhg",
    ssl: { rejectUnauthorized: false },
  });

  await client.connect();
  console.log("Connected to RDS via SSH tunnel\n");

  // First, clean up any partial data from previous runs
  console.log("Cleaning up partial data from previous runs...");
  const cleanup = [
    "DELETE FROM public.products",
    "DELETE FROM public.rules",
    "DELETE FROM public.members",
    "DELETE FROM public.hierarchy",
    "DELETE FROM public.units",
    'DELETE FROM public."Chat_Agents"',
    'DELETE FROM public."Workspaces"',
    "DELETE FROM public.auth_users",
    "DELETE FROM public.profiles",
  ];
  for (const sql of cleanup) {
    try { await client.query(sql); } catch(e) { /* ignore */ }
  }
  console.log("Cleanup done.\n");

  // Now run sections in order
  const sections = [
    {
      name: "Disable auth trigger",
      sql: "DROP TRIGGER IF EXISTS trigger_auth_user_created ON public.auth_users"
    },
    {
      name: "Profiles",
      file: true,
      match: /-- 1\. Profiles/,
      end: /-- ={5,}/,
      sectionIdx: 0
    },
    {
      name: "Auth Users",
      file: true,
      sectionIdx: 1
    },
    {
      name: "Workspaces",
      file: true,
      sectionIdx: 2
    },
    {
      name: "Chat Agents (ALTER + INSERT)",
      file: true,
      sectionIdx: 3
    },
    {
      name: "Hierarchy",
      file: true,
      sectionIdx: 4
    },
    {
      name: "Units",
      file: true,
      sectionIdx: 5
    },
    {
      name: "Members",
      file: true,
      sectionIdx: 6
    },
    {
      name: "Members reports_to updates",
      file: true,
      sectionIdx: 7
    },
    {
      name: "Rules",
      file: true,
      sectionIdx: 8
    },
    {
      name: "Products",
      file: true,
      sectionIdx: 9
    },
    {
      name: "Re-enable auth trigger",
      sql: `CREATE TRIGGER trigger_auth_user_created
    AFTER INSERT ON public.auth_users
    FOR EACH ROW
    EXECUTE FUNCTION public.trigger_new_auth_user()`
    }
  ];

  // Read and split by section headers
  const filePath = path.join(__dirname, "..", "migration", "018_seed_production_data.sql");
  const fullSql = fs.readFileSync(filePath, "utf8");

  // Split by the section headers (lines starting with -- ===)
  const sectionSplitter = /\n-- ={5,}\n-- \d+\./;
  const rawSections = fullSql.split(sectionSplitter);

  // Actually, let's just run the entire file as one query
  // PostgreSQL handles multiple statements in one query() call
  console.log("Running full migration as single query...\n");

  try {
    await client.query(fullSql);
    console.log("SUCCESS! All data seeded successfully.");
  } catch (err) {
    console.error("Error:", err.message);
    console.error("\nPosition:", err.position);
    
    if (err.position) {
      const pos = parseInt(err.position);
      const context = fullSql.substring(Math.max(0, pos - 100), pos + 100);
      console.error("\nContext around error:\n", context);
    }

    // Try running section by section to isolate the error
    console.log("\n\nRetrying section by section...\n");

    // Split file into sections by the === headers
    const sectionRegex = /^-- ={5,}\n-- (\d+\..+)\n-- ={5,}/gm;
    let lastIdx = 0;
    let sectionList = [];
    let match;

    // Find all section boundaries
    const lines = fullSql.split('\n');
    let currentSection = { name: "Preamble", startLine: 0 };
    let sectionBoundaries = [];

    for (let i = 0; i < lines.length; i++) {
      if (lines[i].match(/^-- ={5,}$/) && i + 1 < lines.length && lines[i+1].match(/^-- \d+\./)) {
        if (currentSection) {
          currentSection.endLine = i - 1;
          sectionBoundaries.push(currentSection);
        }
        currentSection = { name: lines[i+1].replace(/^-- /, ''), startLine: i };
      }
    }
    if (currentSection) {
      currentSection.endLine = lines.length - 1;
      sectionBoundaries.push(currentSection);
    }

    for (const section of sectionBoundaries) {
      const sectionSql = lines.slice(section.startLine, section.endLine + 1).join('\n');
      if (sectionSql.trim().length === 0) continue;
      if (sectionSql.split('\n').every(l => l.trim().startsWith('--') || l.trim() === '')) continue;

      try {
        await client.query(sectionSql);
        console.log(`  [OK]  ${section.name}`);
      } catch (e) {
        console.error(`  [ERR] ${section.name}: ${e.message}`);
        if (e.position) {
          const pos = parseInt(e.position);
          const ctx = sectionSql.substring(Math.max(0, pos - 50), pos + 50);
          console.error(`        Near: ...${ctx}...`);
        }
      }
    }
  }

  await client.end();
  console.log("\nDone!");
}

run().catch((e) => {
  console.error("Fatal:", e.message);
  process.exit(1);
});
