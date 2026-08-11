namespace Yap.Verification
{
    using System;
    using System.Collections.Generic;
    using System.IO;
    using System.Runtime.InteropServices;
    using System.Text;

    public static partial class WindowsCommandJobSupervisor
    {
        private static void ValidateRequest(
            string executablePath,
            string[] arguments,
            string workingDirectory,
            string[] environmentEntries,
            string statusPath,
            string supervisorIdentitySha256,
            string environmentSha256,
            string launchNonce,
            string launchSpecSha256,
            int naturalDescendantDrainMilliseconds,
            int cleanupTimeoutMilliseconds)
        {
            if (string.IsNullOrEmpty(executablePath)
                || !Path.IsPathFullyQualified(executablePath)
                || !File.Exists(executablePath))
            {
                throw new ArgumentException("The executable path must identify an absolute file.");
            }
            if (arguments == null)
                throw new ArgumentNullException(nameof(arguments));
            foreach (string argument in arguments)
            {
                if (argument == null || argument.IndexOf('\0') >= 0)
                    throw new ArgumentException("Arguments must be non-null and must not contain NUL.");
            }
            if (string.IsNullOrEmpty(workingDirectory)
                || !Path.IsPathFullyQualified(workingDirectory)
                || !Directory.Exists(workingDirectory))
            {
                throw new ArgumentException("The working directory must identify an absolute directory.");
            }
            if (string.IsNullOrEmpty(statusPath)
                || !Path.IsPathFullyQualified(statusPath)
                || File.Exists(statusPath))
            {
                throw new ArgumentException("The status path must be unused and absolute.");
            }
            ValidateEnvironment(environmentEntries);
            ValidateLowerHex(supervisorIdentitySha256, "supervisor identity SHA-256");
            ValidateLowerHex(environmentSha256, "environment SHA-256");
            ValidateLowerHex(launchNonce, "launch nonce");
            ValidateLowerHex(launchSpecSha256, "launch-specification SHA-256");
            if (naturalDescendantDrainMilliseconds < 1_000
                || naturalDescendantDrainMilliseconds > 30_000)
            {
                throw new ArgumentOutOfRangeException(
                    nameof(naturalDescendantDrainMilliseconds));
            }
            if (cleanupTimeoutMilliseconds < 1_000 || cleanupTimeoutMilliseconds > 10_000)
                throw new ArgumentOutOfRangeException(nameof(cleanupTimeoutMilliseconds));
        }

        private static void ValidateEnvironment(string[] entries)
        {
            if (entries == null)
                throw new ArgumentNullException(nameof(entries));
            HashSet<string> names = new HashSet<string>(
                StringComparer.OrdinalIgnoreCase);
            int blockCharacters = 1;
            foreach (string entry in entries)
            {
                int separator = entry == null ? -1 : entry.IndexOf('=');
                if (separator < 1 || entry.IndexOf('\0') >= 0)
                    throw new ArgumentException(
                        "Environment entries must use non-empty NAME=VALUE strings without NUL.");
                string name = entry.Substring(0, separator);
                if (!names.Add(name))
                    throw new ArgumentException(
                        "Environment variable names must be case-insensitively unique.");
                blockCharacters = checked(blockCharacters + entry.Length + 1);
            }
            if (blockCharacters > 32767)
                throw new ArgumentException(
                    "The Windows environment block exceeds 32,767 UTF-16 characters.");
        }

        private static IntPtr BuildEnvironmentBlock(string[] entries)
        {
            string[] sorted = (string[])entries.Clone();
            Array.Sort(sorted, StringComparer.OrdinalIgnoreCase);
            string block = string.Join("\0", sorted) + "\0\0";
            return Marshal.StringToHGlobalUni(block);
        }

        private static void ValidateLowerHex(string value, string label)
        {
            if (value == null || value.Length != 64)
                throw new ArgumentException(
                    "The " + label + " must contain 64 hexadecimal characters.");
            foreach (char character in value)
            {
                if (!((character >= '0' && character <= '9')
                    || (character >= 'a' && character <= 'f')))
                {
                    throw new ArgumentException(
                        "The " + label + " must be lowercase hexadecimal.");
                }
            }
        }

        private static string BuildWindowsCommandLine(string executablePath, string[] arguments)
        {
            if (StringComparer.OrdinalIgnoreCase.Equals(
                Path.GetFileName(executablePath),
                "cmd.exe")
                && arguments.Length == 4
                && StringComparer.OrdinalIgnoreCase.Equals(arguments[0], "/d")
                && StringComparer.OrdinalIgnoreCase.Equals(arguments[1], "/s")
                && StringComparer.OrdinalIgnoreCase.Equals(arguments[2], "/c"))
            {
                if (arguments[3].IndexOfAny(new[] { '\r', '\n', '\0' }) >= 0)
                    throw new ArgumentException("The cmd.exe command must not contain CR, LF, or NUL.");
                string cmdLine = QuoteWindowsArgument(executablePath)
                    + " /d /s /c \"" + arguments[3] + "\"";
                if (cmdLine.Length + 1 > 32767)
                    throw new ArgumentException(
                        "The Windows command line exceeds 32,767 UTF-16 characters.");
                return cmdLine;
            }

            StringBuilder commandLine = new StringBuilder();
            commandLine.Append(QuoteWindowsArgument(executablePath));
            foreach (string argument in arguments)
                commandLine.Append(' ').Append(QuoteWindowsArgument(argument));
            if (commandLine.Length + 1 > 32767)
                throw new ArgumentException("The Windows command line exceeds 32,767 UTF-16 characters.");
            return commandLine.ToString();
        }

        private static string QuoteWindowsArgument(string argument)
        {
            bool quote = argument.Length == 0;
            foreach (char value in argument)
            {
                if (char.IsWhiteSpace(value) || value == '"')
                {
                    quote = true;
                    break;
                }
            }
            if (!quote)
                return argument;

            StringBuilder quoted = new StringBuilder("\"");
            int backslashes = 0;
            foreach (char value in argument)
            {
                if (value == '\\')
                {
                    backslashes++;
                    continue;
                }
                if (value == '"')
                {
                    quoted.Append('\\', checked(backslashes * 2 + 1));
                    quoted.Append('"');
                    backslashes = 0;
                    continue;
                }
                quoted.Append('\\', backslashes);
                quoted.Append(value);
                backslashes = 0;
            }
            quoted.Append('\\', checked(backslashes * 2));
            return quoted.Append('"').ToString();
        }

    }
}
