using System;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

namespace Yap.Verification
{
    public static partial class WindowsCommandJobSupervisor
    {
        private const uint CreateSuspended = 0x00000004;
        private const uint CreateUnicodeEnvironment = 0x00000400;
        private const uint CreateNoWindow = 0x08000000;
        private const uint ExtendedStartupInfoPresent = 0x00080000;
        private const uint StartfUseShowWindow = 0x00000001;
        private const uint StartfUseStdHandles = 0x00000100;
        private const ushort SwHide = 0;
        private const uint JobObjectLimitKillOnJobClose = 0x00002000;
        private const int JobObjectExtendedLimitInformationClass = 9;
        private const int JobObjectBasicAccountingInformationClass = 1;
        private const int ProcThreadAttributeHandleList = 0x00020002;
        private const uint DuplicateSameAccess = 0x00000002;
        private const uint GenericRead = 0x80000000;
        private const uint FileShareRead = 0x00000001;
        private const uint FileShareWrite = 0x00000002;
        private const uint OpenExisting = 3;
        private const uint FileAttributeNormal = 0x00000080;
        private const int StdOutputHandle = -11;
        private const int StdErrorHandle = -12;
        private const uint WaitObject0 = 0;
        private const uint WaitTimeout = 258;
        private const uint Infinite = 0xffffffff;
        private const uint ForcedTerminationExitCode = 0xe0000001;
        private static readonly IntPtr InvalidHandleValue = new IntPtr(-1);

        public static int Run(
            string executablePath,
            string[] arguments,
            string workingDirectory,
            string[] environmentEntries,
            string statusPath,
            string supervisorIdentitySha256,
            string environmentSha256,
            string launchNonce,
            string launchSpecSha256,
            int cleanupTimeoutMilliseconds)
        {
            IntPtr jobHandle = IntPtr.Zero;
            IntPtr processHandle = IntPtr.Zero;
            IntPtr threadHandle = IntPtr.Zero;
            IntPtr standardInput = IntPtr.Zero;
            IntPtr standardOutput = IntPtr.Zero;
            IntPtr standardError = IntPtr.Zero;
            IntPtr attributeList = IntPtr.Zero;
            IntPtr inheritedHandleList = IntPtr.Zero;
            IntPtr commandLine = IntPtr.Zero;
            IntPtr environmentBlock = IntPtr.Zero;
            uint rootProcessId = 0;
            uint? targetExitCode = null;
            bool assignedBeforeResume = false;
            bool rootExited = false;
            bool activeProcessZeroObserved = false;
            bool terminationRequested = false;
            bool retainedDescendantDetected = false;
            uint finalActiveProcessCount = 0;
            Stopwatch elapsed = Stopwatch.StartNew();

            try
            {
                ValidateRequest(
                    executablePath,
                    arguments,
                    workingDirectory,
                    environmentEntries,
                    statusPath,
                    supervisorIdentitySha256,
                    environmentSha256,
                    launchNonce,
                    launchSpecSha256,
                    cleanupTimeoutMilliseconds);
                standardInput = OpenInheritedNullInput();
                standardOutput = DuplicateInheritedStandardHandle(StdOutputHandle);
                standardError = DuplicateInheritedStandardHandle(StdErrorHandle);
                jobHandle = CreateKillOnCloseJob();
                BuildInheritedHandleList(
                    standardInput,
                    standardOutput,
                    standardError,
                    out attributeList,
                    out inheritedHandleList);
                commandLine = Marshal.StringToHGlobalUni(
                    BuildWindowsCommandLine(executablePath, arguments));
                environmentBlock = BuildEnvironmentBlock(environmentEntries);

                StartupInfoEx startup = new StartupInfoEx();
                startup.StartupInfo.Size = Marshal.SizeOf<StartupInfoEx>();
                startup.StartupInfo.Flags = StartfUseShowWindow | StartfUseStdHandles;
                startup.StartupInfo.ShowWindow = SwHide;
                startup.StartupInfo.StandardInput = standardInput;
                startup.StartupInfo.StandardOutput = standardOutput;
                startup.StartupInfo.StandardError = standardError;
                startup.AttributeList = attributeList;

                ProcessInformation process;
                if (!CreateProcessW(
                    executablePath,
                    commandLine,
                    IntPtr.Zero,
                    IntPtr.Zero,
                    true,
                    CreateSuspended
                        | CreateUnicodeEnvironment
                        | CreateNoWindow
                        | ExtendedStartupInfoPresent,
                    environmentBlock,
                    workingDirectory,
                    ref startup,
                    out process))
                {
                    throw LastWin32("CreateProcessW failed.");
                }
                processHandle = process.Process;
                threadHandle = process.Thread;
                rootProcessId = process.ProcessId;

                if (!AssignProcessToJobObject(jobHandle, processHandle))
                    throw LastWin32("AssignProcessToJobObject failed.");
                bool isInJob;
                if (!IsProcessInJob(processHandle, jobHandle, out isInJob))
                    throw LastWin32("IsProcessInJob failed.");
                if (!isInJob)
                    throw new InvalidOperationException("The suspended process was not assigned to its Job Object.");
                assignedBeforeResume = true;

                uint previousSuspendCount = ResumeThread(threadHandle);
                if (previousSuspendCount == Infinite)
                    throw LastWin32("ResumeThread failed.");
                if (previousSuspendCount != 1)
                    throw new InvalidOperationException("ResumeThread returned an unexpected suspend count.");

                CloseHandleChecked(ref threadHandle, "primary thread");
                ReleaseLaunchHandles(
                    ref standardInput,
                    ref standardOutput,
                    ref standardError,
                    ref attributeList,
                    ref inheritedHandleList,
                    ref commandLine,
                    ref environmentBlock);

                int externalTermination = 0;
                Thread controlReader = new Thread(() =>
                {
                    try
                    {
                        string command = Console.In.ReadLine();
                        if (command == null || StringComparer.Ordinal.Equals(command, "T"))
                            Interlocked.Exchange(ref externalTermination, 1);
                        else
                            Interlocked.Exchange(ref externalTermination, 2);
                    }
                    catch
                    {
                        Interlocked.Exchange(ref externalTermination, 2);
                    }
                });
                controlReader.IsBackground = true;
                controlReader.Name = "Yap bounded-command termination control";
                controlReader.Start();

                long? rootExitObservedAt = null;
                long? terminationDeadline = null;
                bool terminationIssued = false;

                while (true)
                {
                    if (!rootExited)
                    {
                        uint wait = WaitForSingleObject(processHandle, 0);
                        if (wait == WaitObject0)
                        {
                            rootExited = true;
                            rootExitObservedAt = elapsed.ElapsedMilliseconds;
                            uint exitCode;
                            if (!GetExitCodeProcess(processHandle, out exitCode))
                                throw LastWin32("GetExitCodeProcess failed.");
                            targetExitCode = exitCode;
                        }
                        else if (wait != WaitTimeout)
                        {
                            throw LastWin32("Waiting for the root process failed.");
                        }
                    }

                    int controlState = Volatile.Read(ref externalTermination);
                    if (controlState != 0 && !terminationIssued)
                    {
                        terminationRequested = true;
                        terminationIssued = true;
                        terminationDeadline = checked(
                            elapsed.ElapsedMilliseconds + cleanupTimeoutMilliseconds);
                        if (!TerminateJobObject(jobHandle, ForcedTerminationExitCode))
                        {
                            finalActiveProcessCount = QueryActiveProcessCount(jobHandle);
                            if (finalActiveProcessCount != 0)
                                throw LastWin32("TerminateJobObject failed.");
                        }
                    }

                    finalActiveProcessCount = QueryActiveProcessCount(jobHandle);
                    if (finalActiveProcessCount == 0)
                        activeProcessZeroObserved = true;
                    if (rootExited && finalActiveProcessCount == 0)
                    {
                        break;
                    }

                    if (!terminationIssued
                        && rootExited
                        && rootExitObservedAt.HasValue
                        && finalActiveProcessCount > 0
                        && elapsed.ElapsedMilliseconds - rootExitObservedAt.Value >= 250)
                    {
                        retainedDescendantDetected = true;
                        terminationRequested = true;
                        terminationIssued = true;
                        terminationDeadline = checked(
                            elapsed.ElapsedMilliseconds + cleanupTimeoutMilliseconds);
                        if (!TerminateJobObject(jobHandle, ForcedTerminationExitCode))
                        {
                            finalActiveProcessCount = QueryActiveProcessCount(jobHandle);
                            if (finalActiveProcessCount != 0)
                                throw LastWin32("Terminating retained descendants failed.");
                        }
                    }

                    if (terminationIssued
                        && terminationDeadline.HasValue
                        && elapsed.ElapsedMilliseconds >= terminationDeadline.Value)
                    {
                        break;
                    }
                    Thread.Sleep(20);
                }

                finalActiveProcessCount = QueryActiveProcessCount(jobHandle);
                if (finalActiveProcessCount == 0)
                    activeProcessZeroObserved = true;
                bool cleanupProven = rootExited && finalActiveProcessCount == 0;
                string outcome = cleanupProven
                    ? retainedDescendantDetected
                        ? "retained-descendant"
                        : terminationRequested
                            ? "terminated"
                            : "completed"
                    : "cleanup-unproven";
                WriteStatus(
                    statusPath,
                    supervisorIdentitySha256,
                    environmentSha256,
                    launchNonce,
                    launchSpecSha256,
                    outcome,
                    rootProcessId,
                    assignedBeforeResume,
                    targetExitCode,
                    terminationRequested,
                    rootExited,
                    finalActiveProcessCount,
                    activeProcessZeroObserved,
                    cleanupProven,
                    retainedDescendantDetected,
                    elapsed.ElapsedMilliseconds,
                    null);
                return 0;
            }
            catch (Exception error)
            {
                bool cleanupProven = CleanupFailedLaunch(
                    jobHandle,
                    processHandle,
                    cleanupTimeoutMilliseconds,
                    assignedBeforeResume,
                    ref rootExited,
                    ref activeProcessZeroObserved,
                    out finalActiveProcessCount);
                try
                {
                    WriteStatus(
                        statusPath,
                        supervisorIdentitySha256,
                        environmentSha256,
                        launchNonce,
                        launchSpecSha256,
                        "supervisor-failure",
                        rootProcessId,
                        assignedBeforeResume,
                        targetExitCode,
                        true,
                        rootExited,
                        finalActiveProcessCount,
                        activeProcessZeroObserved,
                        cleanupProven,
                        retainedDescendantDetected,
                        elapsed.ElapsedMilliseconds,
                        error is Win32Exception
                            ? ((Win32Exception)error).NativeErrorCode
                            : (int?)null);
                    return 0;
                }
                catch
                {
                    return 1;
                }
            }
            finally
            {
                ReleaseLaunchHandles(
                    ref standardInput,
                    ref standardOutput,
                    ref standardError,
                    ref attributeList,
                    ref inheritedHandleList,
                    ref commandLine,
                    ref environmentBlock);
                CloseHandleNoThrow(ref threadHandle);
                CloseHandleNoThrow(ref processHandle);
                CloseHandleNoThrow(ref jobHandle);
            }
        }

    }
}
