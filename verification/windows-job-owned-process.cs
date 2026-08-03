namespace Yap.Verification
{
    using System;
    using System.ComponentModel;
    using System.Diagnostics;
    using System.Runtime.InteropServices;
    using System.Text;

    public static partial class WindowsCommandJobSupervisor
    {
        private static IntPtr OpenInheritedNullInput()
        {
            SecurityAttributes security = new SecurityAttributes();
            security.Length = Marshal.SizeOf<SecurityAttributes>();
            security.InheritHandle = true;
            IntPtr handle = CreateFileW(
                "NUL",
                GenericRead,
                FileShareRead | FileShareWrite,
                ref security,
                OpenExisting,
                FileAttributeNormal,
                IntPtr.Zero);
            if (handle == InvalidHandleValue)
                throw LastWin32("Opening NUL for standard input failed.");
            return handle;
        }

        private static IntPtr DuplicateInheritedStandardHandle(int standardHandle)
        {
            IntPtr source = GetStdHandle(standardHandle);
            if (source == IntPtr.Zero || source == InvalidHandleValue)
                throw LastWin32("A supervisor standard handle was unavailable.");
            IntPtr currentProcess = GetCurrentProcess();
            IntPtr duplicate;
            if (!DuplicateHandle(
                currentProcess,
                source,
                currentProcess,
                out duplicate,
                0,
                true,
                DuplicateSameAccess))
            {
                throw LastWin32("Duplicating a supervisor standard handle failed.");
            }
            return duplicate;
        }

        private static IntPtr CreateKillOnCloseJob()
        {
            IntPtr job = CreateJobObjectW(IntPtr.Zero, null);
            if (job == IntPtr.Zero)
                throw LastWin32("CreateJobObjectW failed.");
            JobObjectExtendedLimitInformation limits = new JobObjectExtendedLimitInformation();
            limits.BasicLimitInformation.LimitFlags = JobObjectLimitKillOnJobClose;
            if (!SetInformationJobObject(
                job,
                JobObjectExtendedLimitInformationClass,
                ref limits,
                (uint)Marshal.SizeOf<JobObjectExtendedLimitInformation>()))
            {
                int error = Marshal.GetLastWin32Error();
                CloseHandle(job);
                throw new Win32Exception(error, "Configuring JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE failed.");
            }
            return job;
        }

        private static void BuildInheritedHandleList(
            IntPtr standardInput,
            IntPtr standardOutput,
            IntPtr standardError,
            out IntPtr attributeList,
            out IntPtr inheritedHandleList)
        {
            attributeList = IntPtr.Zero;
            inheritedHandleList = IntPtr.Zero;
            IntPtr requiredBytes = IntPtr.Zero;
            InitializeProcThreadAttributeList(IntPtr.Zero, 1, 0, ref requiredBytes);
            if (requiredBytes == IntPtr.Zero)
                throw LastWin32("Sizing the process attribute list failed.");

            attributeList = Marshal.AllocHGlobal(requiredBytes);
            if (!InitializeProcThreadAttributeList(attributeList, 1, 0, ref requiredBytes))
            {
                int error = Marshal.GetLastWin32Error();
                Marshal.FreeHGlobal(attributeList);
                attributeList = IntPtr.Zero;
                throw new Win32Exception(
                    error,
                    "Initializing the process attribute list failed.");
            }

            inheritedHandleList = Marshal.AllocHGlobal(checked(IntPtr.Size * 3));
            Marshal.WriteIntPtr(inheritedHandleList, 0, standardInput);
            Marshal.WriteIntPtr(inheritedHandleList, IntPtr.Size, standardOutput);
            Marshal.WriteIntPtr(inheritedHandleList, IntPtr.Size * 2, standardError);
            if (!UpdateProcThreadAttribute(
                attributeList,
                0,
                new IntPtr(ProcThreadAttributeHandleList),
                inheritedHandleList,
                new IntPtr(checked(IntPtr.Size * 3)),
                IntPtr.Zero,
                IntPtr.Zero))
            {
                throw LastWin32("Installing the inherited-handle allowlist failed.");
            }
        }

        private static uint QueryActiveProcessCount(IntPtr job)
        {
            JobObjectBasicAccountingInformation accounting;
            if (!QueryInformationJobObject(
                job,
                JobObjectBasicAccountingInformationClass,
                out accounting,
                (uint)Marshal.SizeOf<JobObjectBasicAccountingInformation>(),
                IntPtr.Zero))
            {
                throw LastWin32("QueryInformationJobObject failed.");
            }
            return accounting.ActiveProcesses;
        }

        private static string[] QueryActiveProcessNames(IntPtr job)
        {
            const int maximumProcessCount = 128;
            try
            {
                uint activeProcessCount = QueryActiveProcessCount(job);
                int capacity = checked((int)Math.Min(
                    Math.Max(activeProcessCount + 8u, 16u),
                    (uint)maximumProcessCount));
                for (int attempt = 0; attempt < 4; attempt += 1)
                {
                    int bufferBytes = checked(8 + capacity * IntPtr.Size);
                    IntPtr buffer = Marshal.AllocHGlobal(bufferBytes);
                    try
                    {
                        for (int offset = 0; offset < bufferBytes; offset += 1)
                            Marshal.WriteByte(buffer, offset, 0);
                        if (QueryInformationJobObjectProcessIds(
                            job,
                            JobObjectBasicProcessIdListClass,
                            buffer,
                            (uint)bufferBytes,
                            IntPtr.Zero))
                        {
                            uint processCount = unchecked((uint)Marshal.ReadInt32(buffer, 4));
                            if (processCount == 0)
                                return new[] { "unavailable" };
                            int boundedCount = checked((int)Math.Min(
                                processCount,
                                (uint)capacity));
                            string[] names = new string[boundedCount];
                            for (int index = 0; index < boundedCount; index += 1)
                            {
                                long processId = Marshal.ReadIntPtr(
                                    buffer,
                                    checked(8 + index * IntPtr.Size)).ToInt64();
                                names[index] = QuerySafeProcessName(processId);
                            }
                            Array.Sort(names, StringComparer.Ordinal);
                            return names;
                        }

                        uint assignedProcessCount = unchecked(
                            (uint)Marshal.ReadInt32(buffer, 0));
                        if (capacity >= maximumProcessCount)
                            break;
                        capacity = checked((int)Math.Min(
                            Math.Max(assignedProcessCount + 8u, (uint)capacity * 2u),
                            (uint)maximumProcessCount));
                    }
                    finally
                    {
                        Marshal.FreeHGlobal(buffer);
                    }
                }
            }
            catch
            {
                // Diagnostics must never prevent the owned Job from being terminated.
            }
            return new[] { "unavailable" };
        }

        private static string QuerySafeProcessName(long processId)
        {
            if (processId <= 0 || processId > int.MaxValue)
                return "unavailable";
            try
            {
                using (Process process = Process.GetProcessById((int)processId))
                {
                    string name = process.ProcessName.ToLowerInvariant();
                    if (name.Length == 0 || name.Length > 128)
                        return "unavailable";
                    StringBuilder safe = new StringBuilder(name.Length);
                    foreach (char value in name)
                    {
                        safe.Append(
                            value >= 'a' && value <= 'z'
                                || value >= '0' && value <= '9'
                                || value == '.'
                                || value == '_'
                                || value == '-'
                                ? value
                                : '_');
                    }
                    return safe.ToString();
                }
            }
            catch
            {
                return "unavailable";
            }
        }

        private static bool CleanupFailedLaunch(
            IntPtr job,
            IntPtr process,
            int timeoutMilliseconds,
            bool assignedToJob,
            ref bool rootExited,
            ref bool activeProcessZeroObserved,
            out uint activeProcessCount)
        {
            activeProcessCount = 0;
            if (job == IntPtr.Zero)
            {
                if (process == IntPtr.Zero)
                    return true;
                if (!TerminateProcess(process, ForcedTerminationExitCode))
                    return false;
                rootExited = WaitForSingleObject(
                    process,
                    (uint)timeoutMilliseconds) == WaitObject0;
                return rootExited;
            }
            try
            {
                if (process == IntPtr.Zero)
                {
                    activeProcessCount = QueryActiveProcessCount(job);
                    activeProcessZeroObserved = activeProcessCount == 0;
                    return activeProcessCount == 0;
                }
                if (!assignedToJob)
                {
                    if (!TerminateProcess(process, ForcedTerminationExitCode))
                        return false;
                    rootExited = WaitForSingleObject(
                        process,
                        (uint)timeoutMilliseconds) == WaitObject0;
                    activeProcessCount = QueryActiveProcessCount(job);
                    activeProcessZeroObserved = activeProcessCount == 0;
                    return rootExited && activeProcessCount == 0;
                }
                if (!TerminateJobObject(job, ForcedTerminationExitCode))
                {
                    activeProcessCount = QueryActiveProcessCount(job);
                    if (activeProcessCount != 0)
                        return false;
                }
                Stopwatch cleanup = Stopwatch.StartNew();
                while (cleanup.ElapsedMilliseconds < timeoutMilliseconds)
                {
                    if (process != IntPtr.Zero && !rootExited)
                        rootExited = WaitForSingleObject(process, 0) == WaitObject0;
                    activeProcessCount = QueryActiveProcessCount(job);
                    if (activeProcessCount == 0)
                        activeProcessZeroObserved = true;
                    if ((process == IntPtr.Zero || rootExited) && activeProcessCount == 0)
                    {
                        return true;
                    }
                    System.Threading.Thread.Sleep(20);
                }
                activeProcessCount = QueryActiveProcessCount(job);
                if (activeProcessCount == 0)
                    activeProcessZeroObserved = true;
                return false;
            }
            catch
            {
                return false;
            }
        }

    }
}
