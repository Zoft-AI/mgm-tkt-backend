const { Client } = require("pg");
const fs = require("fs");
const path = require("path");

const MIGRATIONS = [
  "002_core_tables.sql",
  "003_hierarchy.sql",
  "004_units.sql",
  "005_members.sql",
  "006_rules.sql",
  "007_requests.sql",
  "008_products.sql",
  "009_file_attachments.sql",
  "010_functions.sql",
  "015_auth_users.sql",
  "016_auth_refresh_tokens.sql",
  "017_auth_triggers.sql",
];

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

  for (const file of MIGRATIONS) {
    const filePath = path.join(__dirname, "..", "migration", file);
    const sql = fs.readFileSync(filePath, "utf8");

    try {
      await client.query(sql);
      console.log(`  [OK]  ${file}`);
    } catch (err) {
      console.error(`  [ERR] ${file}: ${err.message}`);
    }
  }

  console.log("\nDone! All migrations executed.");
  await client.end();
}

run().catch((e) => {
  console.error("Fatal:", e.message);
  process.exit(1);
});
