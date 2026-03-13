# Only showing the critical fix section around line 650

# At line 650, change from:
# cmd = [acpx_bin, "claude", "exec", prompt]
# To:
# cmd = [acpx_bin, "claude", "exec"]
# result = subprocess.run(cmd, input=prompt, ...)

                acpx_bin = "/usr/lib/node_modules/openclaw/extensions/acpx/node_modules/acpx/dist/cli.js"
                
                # Log command for debugging
                cmd_str = f"{' '.join([acpx_bin, 'claude', 'exec'])}"
                print(f"🔴 ACPX-V2-SUBPROCESS-PRE: Command: {cmd_str}")
                print(f"🔴 ACPX-V2-SUBPROCESS-PRE: Prompt length: {len(prompt)} chars")
                print(f"🔴 ACPX-V2-SUBPROCESS-PRE: Timeout: {BUILD_TIMEOUT}s")
                print(f"🔴 ACPX-V2-SUBPROCESS-PRE: Working dir: {self.frontend_src_path}")

                # CRITICAL FIX: Use input= parameter, NOT command argument
                result = subprocess.run(
                    [acpx_bin, "claude", "exec"],
                    input=prompt,
                    capture_output=True,
                    timeout=BUILD_TIMEOUT,
                    cwd=self.frontend_src_path
                )
