namespace Yap.Verification
{
    using System;
    using System.ComponentModel;
    using System.IO;
    using System.Runtime.InteropServices;
    using System.Text;

    public static partial class WindowsCommandJobSupervisor
    {
        private static void WriteStatus(
            string path,
            string supervisorIdentitySha256,
            string environmentSha256,
            string launchNonce,
            string launchSpecSha256,
            string outcome,
            uint rootProcessId,
            bool assignedBeforeResume,
            uint? targetExitCode,
            bool terminationRequested,
            bool rootExited,
            uint activeProcessCount,
            bool activeProcessZeroObserved,
            bool cleanupProven,
            bool retainedDescendantDetected,
            string[] retainedProcessNames,
            long elapsedMilliseconds,
            int? nativeErrorCode)
        {
            string json = "{\n"
                + "  \"schemaVersion\": 2,\n"
                + "  \"containment\": \"windows-job-object\",\n"
                + "  \"supervisorIdentitySha256\": \"" + supervisorIdentitySha256 + "\",\n"
                + "  \"environmentSha256\": \"" + environmentSha256 + "\",\n"
                + "  \"launchNonce\": \"" + launchNonce + "\",\n"
                + "  \"launchSpecSha256\": \"" + launchSpecSha256 + "\",\n"
                + "  \"outcome\": \"" + outcome + "\",\n"
                + "  \"rootProcessId\": " + rootProcessId + ",\n"
                + "  \"assignedBeforeResume\": " + JsonBoolean(assignedBeforeResume) + ",\n"
                + "  \"targetExitCode\": "
                    + (targetExitCode.HasValue ? targetExitCode.Value.ToString() : "null") + ",\n"
                + "  \"terminationRequested\": " + JsonBoolean(terminationRequested) + ",\n"
                + "  \"rootExited\": " + JsonBoolean(rootExited) + ",\n"
                + "  \"activeProcessCount\": " + activeProcessCount + ",\n"
                + "  \"activeProcessZeroObserved\": "
                    + JsonBoolean(activeProcessZeroObserved) + ",\n"
                + "  \"cleanupProven\": " + JsonBoolean(cleanupProven) + ",\n"
                + "  \"retainedDescendantDetected\": "
                    + JsonBoolean(retainedDescendantDetected) + ",\n"
                + "  \"retainedProcessNames\": "
                    + JsonStringArray(retainedProcessNames) + ",\n"
                + "  \"elapsedMilliseconds\": " + elapsedMilliseconds + ",\n"
                + "  \"nativeErrorCode\": "
                    + (nativeErrorCode.HasValue ? nativeErrorCode.Value.ToString() : "null") + "\n"
                + "}\n";
            using (FileStream stream = new FileStream(
                path,
                FileMode.CreateNew,
                FileAccess.Write,
                FileShare.None))
            using (StreamWriter writer = new StreamWriter(stream, new UTF8Encoding(false)))
            {
                writer.Write(json);
            }
        }

        private static string JsonBoolean(bool value) => value ? "true" : "false";

        private static string JsonStringArray(string[] values)
        {
            StringBuilder builder = new StringBuilder("[");
            for (int index = 0; index < values.Length; index += 1)
            {
                if (index > 0)
                    builder.Append(',');
                builder.Append('"').Append(values[index]).Append('"');
            }
            return builder.Append(']').ToString();
        }

        private static void ReleaseLaunchHandles(
            ref IntPtr standardInput,
            ref IntPtr standardOutput,
            ref IntPtr standardError,
            ref IntPtr attributeList,
            ref IntPtr inheritedHandleList,
            ref IntPtr commandLine,
            ref IntPtr environmentBlock)
        {
            CloseHandleNoThrow(ref standardInput);
            CloseHandleNoThrow(ref standardOutput);
            CloseHandleNoThrow(ref standardError);
            if (attributeList != IntPtr.Zero)
            {
                try { DeleteProcThreadAttributeList(attributeList); } catch { }
                try { Marshal.FreeHGlobal(attributeList); } catch { }
                attributeList = IntPtr.Zero;
            }
            if (inheritedHandleList != IntPtr.Zero)
            {
                try { Marshal.FreeHGlobal(inheritedHandleList); } catch { }
                inheritedHandleList = IntPtr.Zero;
            }
            if (commandLine != IntPtr.Zero)
            {
                try { Marshal.FreeHGlobal(commandLine); } catch { }
                commandLine = IntPtr.Zero;
            }
            if (environmentBlock != IntPtr.Zero)
            {
                try { Marshal.FreeHGlobal(environmentBlock); } catch { }
                environmentBlock = IntPtr.Zero;
            }
        }

        private static void CloseHandleChecked(ref IntPtr handle, string resource)
        {
            if (handle == IntPtr.Zero)
                return;
            IntPtr value = handle;
            handle = IntPtr.Zero;
            if (!CloseHandle(value))
                throw LastWin32("Closing the " + resource + " handle failed.");
        }

        private static void CloseHandleNoThrow(ref IntPtr handle)
        {
            if (handle == IntPtr.Zero || handle == InvalidHandleValue)
            {
                handle = IntPtr.Zero;
                return;
            }
            IntPtr value = handle;
            handle = IntPtr.Zero;
            try { CloseHandle(value); } catch { }
        }

        private static Win32Exception LastWin32(string message) =>
            new Win32Exception(Marshal.GetLastWin32Error(), message);

    }
}
