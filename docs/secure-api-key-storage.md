# Secure API Key Storage

The default setup for kagimcp requires placing your `KAGI_API_KEY` as plain text in configuration files, CLI arguments, or environment variables. This is convenient but carries risks: keys can be accidentally committed to version control, leaked in shell history, or exposed in process listings.

This guide covers three more secure alternatives for managing your Kagi API key.

---

## Table of Contents

- [Approach 1: macOS Keychain](#approach-1-macos-keychain)
- [Approach 2: Secret Manager / Pass (cross-platform)](#approach-2-secret-manager--pass-cross-platform)
- [Approach 3: Encrypted .env File with SOPS](#approach-3-encrypted-env-file-with-sops)
- [Comparison](#comparison)

---

## Approach 1: macOS Keychain

**Platform:** macOS

Apple Keychain is the native credential store on macOS. It encrypts secrets at rest using your login password and provides access control per-application.

### Store your key

```bash
security add-generic-password \
  -a "$USER" \
  -s "kagi-api-key" \
  -w "YOUR_API_KEY_HERE"
```

### Retrieve your key

```bash
security find-generic-password -a "$USER" -s "kagi-api-key" -w
```

### Use with kagimcp

#### Claude Desktop (`claude_desktop_config.json`)

You cannot embed shell commands directly in the JSON config. Instead, use a wrapper script.

Create `~/.local/bin/kagimcp-wrapper.sh`:

```bash
#!/usr/bin/env bash
export KAGI_API_KEY="$(security find-generic-password -a "$USER" -s "kagi-api-key" -w)"
exec uvx kagimcp "$@"
```

```bash
chmod +x ~/.local/bin/kagimcp-wrapper.sh
```

Then configure Claude Desktop:

```json
{
  "mcpServers": {
    "kagi": {
      "command": "/Users/YOUR_USERNAME/.local/bin/kagimcp-wrapper.sh",
      "args": []
    }
  }
}
```

#### Claude Code

```bash
claude mcp add kagi \
  -e KAGI_API_KEY="$(security find-generic-password -a "$USER" -s "kagi-api-key" -w)" \
  -- uvx kagimcp
```

The key is resolved at the time you run the command and stored in Claude Code's config. To rotate keys, update the Keychain entry and re-run the command above.

### Removing the key

```bash
security delete-generic-password -a "$USER" -s "kagi-api-key"
```

---

## Approach 2: Secret Manager / Pass (cross-platform)

**Platform:** Linux, macOS, WSL

[`pass`](https://www.passwordstore.org/) is the standard Unix password manager. It stores each secret as a GPG-encrypted file inside `~/.password-store/`. It works on Linux, macOS (via Homebrew), and WSL.

### Prerequisites

```bash
# macOS
brew install pass gnupg

# Debian/Ubuntu
sudo apt install pass gnupg

# Fedora
sudo dnf install pass gnupg2
```

### One-time setup

If you do not already have a GPG key:

```bash
gpg --full-generate-key
```

Initialize the password store with your GPG key ID:

```bash
pass init "YOUR_GPG_KEY_ID"
```

### Store your key

```bash
pass insert kagi/api-key
# You will be prompted to enter and confirm the key.
```

### Retrieve your key

```bash
pass show kagi/api-key
```

### Use with kagimcp

#### Wrapper script (`~/.local/bin/kagimcp-wrapper.sh`)

```bash
#!/usr/bin/env bash
export KAGI_API_KEY="$(pass show kagi/api-key)"
exec uvx kagimcp "$@"
```

```bash
chmod +x ~/.local/bin/kagimcp-wrapper.sh
```

Then reference the wrapper in your Claude Desktop config:

```json
{
  "mcpServers": {
    "kagi": {
      "command": "/home/YOUR_USERNAME/.local/bin/kagimcp-wrapper.sh",
      "args": []
    }
  }
}
```

#### Claude Code

```bash
claude mcp add kagi \
  -e KAGI_API_KEY="$(pass show kagi/api-key)" \
  -- uvx kagimcp
```

### Advantages of `pass`

- Secrets are encrypted with your GPG key -- no plaintext files on disk.
- The password store is a regular Git repo, so you can sync encrypted secrets across machines.
- Integrates with `gpg-agent` for cached passphrase entry.
- Ecosystem of extensions and GUIs (e.g., `qtpass`, `browserpass`).

---

## Approach 3: Encrypted `.env` File with SOPS

**Platform:** Linux, macOS, Windows

[SOPS](https://github.com/getsops/sops) (Secrets OPerationS) by Mozilla encrypts and decrypts files while keeping the structure readable. It supports `age`, `gpg`, AWS KMS, GCP KMS, and Azure Key Vault as encryption backends.

This approach is useful when you want to keep configuration in a file (e.g., for team sharing or CI/CD) without exposing secrets in plaintext.

### Prerequisites

```bash
# macOS
brew install sops age

# Linux (using Go)
go install github.com/getsops/sops/v3/cmd/sops@latest
# Install age: https://github.com/FiloSottile/age#installation
```

### One-time setup

Generate an `age` key (simpler alternative to GPG):

```bash
age-keygen -o ~/.config/sops/age/keys.txt
```

Note the public key printed to stdout (starts with `age1...`).

Create a `.sops.yaml` in your project or home directory:

```yaml
creation_rules:
  - path_regex: \.env\.enc$
    age: "age1your_public_key_here"
```

### Encrypt your API key

Create a plaintext `.env` file (temporarily):

```bash
echo 'KAGI_API_KEY=YOUR_API_KEY_HERE' > .env.tmp
```

Encrypt it:

```bash
sops encrypt --input-type dotenv --output-type dotenv .env.tmp > .env.enc
rm .env.tmp
```

The resulting `.env.enc` file contains encrypted values but readable keys. It is safe to commit to version control.

### Decrypt and use with kagimcp

#### Wrapper script (`~/.local/bin/kagimcp-wrapper.sh`)

```bash
#!/usr/bin/env bash
# Decrypt and export variables from the encrypted env file
eval "$(sops decrypt --input-type dotenv --output-type dotenv /path/to/.env.enc)"
export KAGI_API_KEY
exec uvx kagimcp "$@"
```

```bash
chmod +x ~/.local/bin/kagimcp-wrapper.sh
```

Then reference the wrapper in your Claude Desktop config as shown in the previous approaches.

#### One-liner for Claude Code

```bash
claude mcp add kagi \
  -e KAGI_API_KEY="$(sops decrypt --input-type dotenv --output-type dotenv /path/to/.env.enc | grep KAGI_API_KEY | cut -d= -f2)" \
  -- uvx kagimcp
```

### Advantages of SOPS

- Encrypted files are safe to commit -- only people/systems with the decryption key can read the values.
- Supports cloud KMS backends (AWS, GCP, Azure) for team and CI/CD use.
- File structure (key names) remains visible for review, only values are encrypted.
- Can encrypt/decrypt individual values in YAML and JSON files too.

---

## Comparison

| Feature | macOS Keychain | pass (GPG) | SOPS (age/GPG/KMS) |
|---|---|---|---|
| **Platform** | macOS only | Linux, macOS, WSL | Linux, macOS, Windows |
| **Encryption** | AES-256 (system) | GPG | age, GPG, or cloud KMS |
| **Setup complexity** | Low | Medium | Medium |
| **Team/CI-friendly** | No | Partial (Git sync) | Yes (cloud KMS support) |
| **GUI available** | Yes (Keychain Access) | Yes (QtPass) | No |
| **Requires extra tools** | No (built-in) | `gpg`, `pass` | `sops`, `age` or `gpg` |

### Recommendations

- **macOS single-user:** Use Keychain -- zero additional tools, native integration.
- **Linux single-user:** Use `pass` -- standard, well-supported, GPG-encrypted.
- **Teams or CI/CD pipelines:** Use SOPS with a cloud KMS backend -- shareable, auditable, no shared secret keys.

---

## General Security Tips

1. **Never commit plaintext API keys** to version control. Add patterns like `.env`, `*.key`, and `credentials.json` to your `.gitignore`.
2. **Rotate keys periodically** via the [Kagi API settings page](https://kagi.com/settings?p=api).
3. **Use the minimum required scope** when Kagi introduces scoped API keys.
4. **Audit shell history** -- commands containing API keys may be saved in `~/.bash_history` or `~/.zsh_history`. Use a leading space (if `HISTCONTROL=ignorespace` is set) to prevent recording sensitive commands.
5. **Restrict file permissions** on any file that contains or has access to secrets:
   ```bash
   chmod 600 ~/.local/bin/kagimcp-wrapper.sh
   ```
