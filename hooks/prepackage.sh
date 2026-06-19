#!/bin/bash
# Pre-package hook: ensures database is seeded before Docker build
echo "==> Seeding CRM database..."
cd server && python seed_db.py && cd ..
echo "==> CRM database ready."
