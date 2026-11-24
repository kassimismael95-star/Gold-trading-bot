# Gold Scalper Deployment

This document gives step-by-step deployment instructions for Render, Supabase, Oracle A1, and the Oracle x86 MT5 pilot.

All steps can be completed from an Android phone browser.

No local computer is required for management.

## Deployment order

1. Create GitHub repository.
2. Create Supabase project.
3. Create Render service.
4. Deploy control plane.
5. Create Oracle A1 VM.
6. Create Oracle x86 micro VM.
7. Install Wine and MetaTrader 5.
8. Install custom MQL5 EA.
9. Connect demo MT5 account.
10. Run tests.
11. Enable live trading only after explicit authorization.

## 1. Create GitHub repository

On your Android browser:

1. Open GitHub.
2. Create a new repository.
3. Add files through GitHub’s web editor.
4. Commit each file.
5. Add repository secrets only for non-sensitive deployment identifiers where needed.
6. Never add MT5 passwords, database URLs, or signing keys to GitHub.

## 2. Create Supabase project

On your Android browser:

1. Open Supabase.
2. Create a new project.
3. Choose a region close to your users.
4. Create a database password.
5. Save the database URL securely.
6. Enable Row Level Security.
7. Create the required tables using migrations.
8. Set environment variables in Render.

Supabase Free provides:

- 500 MB database size per active project.
- Two active free projects.
- Automatic pausing after one week of low activity.

## 3. Create Render service

On your Android browser:

1. Open Render.
2. Create a new web service.
3. Connect your GitHub repository.
4. Choose the main branch.
5. Set the build command:

```bash
pip install -r requirements.txt
