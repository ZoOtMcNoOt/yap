using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.Identity.Client;
using Microsoft.Identity.Client.Broker;
using Microsoft.Identity.Client.Extensions.Msal;

namespace Yap.Identity.Broker;

internal static class Program
{
    private const ushort SchemaVersion = 1;
    private const int MaximumRequestCharacters = 4 * 1024;
    private const int MaximumIdentityValueCharacters = 1024;

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
        Converters = { new JsonStringEnumConverter(JsonNamingPolicy.CamelCase) },
    };

    public static async Task<int> Main()
    {
        BrokerResponse response;
        try
        {
            var requestText = await ReadBoundedRequestAsync().ConfigureAwait(false);
            var request = JsonSerializer.Deserialize<BrokerRequest>(requestText, JsonOptions);
            response = request is null || !request.IsValid()
                ? BrokerResponse.Invalid(request?.RequestId)
                : await ExecuteAsync(request).ConfigureAwait(false);
        }
        catch
        {
            response = BrokerResponse.Unavailable();
        }

        await Console.Out.WriteAsync(JsonSerializer.Serialize(response, JsonOptions))
            .ConfigureAwait(false);
        return 0;
    }

    private static async Task<string> ReadBoundedRequestAsync()
    {
        var result = new StringBuilder();
        var buffer = new char[1024];
        while (true)
        {
            var count = await Console.In.ReadAsync(buffer).ConfigureAwait(false);
            if (count == 0)
            {
                return result.ToString();
            }
            if (result.Length + count > MaximumRequestCharacters)
            {
                throw new InvalidDataException("Request exceeded the protocol limit.");
            }
            result.Append(buffer, 0, count);
        }
    }

    private static async Task<BrokerResponse> ExecuteAsync(BrokerRequest request)
    {
        try
        {
            var application = PublicClientApplicationBuilder
                .Create(request.ClientId)
                .WithAuthority(AzureCloudInstance.AzurePublic, request.TenantId)
                .WithDefaultRedirectUri()
                .WithBroker(new BrokerOptions(BrokerOptions.OperatingSystems.Windows))
                .Build();
            var cache = await CreateProtectedCacheAsync(request).ConfigureAwait(false);
            cache.RegisterCache(application.UserTokenCache);

            return request.Operation switch
            {
                BrokerOperation.AcquireTokenSilent =>
                    await AcquireTokenSilentAsync(application, request).ConfigureAwait(false),
                BrokerOperation.SignInInteractively =>
                    await SignInInteractivelyAsync(application, request).ConfigureAwait(false),
                BrokerOperation.SignOut =>
                    await SignOutAsync(application, request).ConfigureAwait(false),
                BrokerOperation.GetStatus =>
                    await GetStatusAsync(application, request).ConfigureAwait(false),
                _ => BrokerResponse.Invalid(request.RequestId),
            };
        }
        catch (MsalUiRequiredException)
        {
            return BrokerResponse.InteractionRequired(request.RequestId);
        }
        catch (MsalException)
        {
            return BrokerResponse.Unavailable(request.RequestId);
        }
        catch
        {
            return BrokerResponse.Unavailable(request.RequestId);
        }
    }

    private static async Task<MsalCacheHelper> CreateProtectedCacheAsync(BrokerRequest request)
    {
        var root = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Yap",
            "Identity");
        Directory.CreateDirectory(root);
        var cacheKey = Convert.ToHexString(
            SHA256.HashData(Encoding.UTF8.GetBytes($"{request.TenantId}:{request.ClientId}")))
            .ToLowerInvariant();
        var storage = new StorageCreationPropertiesBuilder(
                $"msal-{cacheKey[..24]}.bin",
                root)
            .Build();
        return await MsalCacheHelper.CreateAsync(storage).ConfigureAwait(false);
    }

    private static async Task<BrokerResponse> AcquireTokenSilentAsync(
        IPublicClientApplication application,
        BrokerRequest request)
    {
        var accounts = (await application.GetAccountsAsync().ConfigureAwait(false)).ToArray();
        if (accounts.Length > 1)
        {
            return BrokerResponse.InteractionRequired(request.RequestId);
        }
        var account = accounts.SingleOrDefault();
        if (account is null)
        {
            return BrokerResponse.InteractionRequired(request.RequestId);
        }
        var result = await application
            .AcquireTokenSilent([request.ApiScope], account)
            .ExecuteAsync()
            .ConfigureAwait(false);
        return BrokerResponse.Token(request, result);
    }

    private static async Task<BrokerResponse> SignInInteractivelyAsync(
        IPublicClientApplication application,
        BrokerRequest request)
    {
        foreach (var account in await application.GetAccountsAsync().ConfigureAwait(false))
        {
            await application.RemoveAsync(account).ConfigureAwait(false);
        }

        var acquisition = application
            .AcquireTokenInteractive([request.ApiScope])
            .WithPrompt(Prompt.SelectAccount);
        if (request.ParentWindowHandle is > 0)
        {
            acquisition = acquisition.WithParentActivityOrWindow(
                new IntPtr(checked((long)request.ParentWindowHandle.Value)));
        }
        var result = await acquisition.ExecuteAsync().ConfigureAwait(false);
        return BrokerResponse.SignedIn(request, result);
    }

    private static async Task<BrokerResponse> SignOutAsync(
        IPublicClientApplication application,
        BrokerRequest request)
    {
        foreach (var account in await application.GetAccountsAsync().ConfigureAwait(false))
        {
            await application.RemoveAsync(account).ConfigureAwait(false);
        }
        return BrokerResponse.SignedOut(request.RequestId);
    }

    private static async Task<BrokerResponse> GetStatusAsync(
        IPublicClientApplication application,
        BrokerRequest request)
    {
        var accounts = await application.GetAccountsAsync().ConfigureAwait(false);
        var accountList = accounts.ToArray();
        if (accountList.Length > 1)
        {
            return BrokerResponse.InteractionRequired(request.RequestId);
        }
        var account = accountList.SingleOrDefault();
        if (account is null)
        {
            return BrokerResponse.SignedOutStatus(request.RequestId);
        }
        return TryTenantAccountId(account, request.TenantId, out var accountId)
            ? BrokerResponse.SignedInStatus(request.RequestId, accountId)
            : BrokerResponse.InteractionRequired(request.RequestId);
    }

    private static bool TryTenantAccountId(
        IAccount account,
        string tenantId,
        out string accountId)
    {
        accountId = string.Empty;
        if (!Guid.TryParse(tenantId, out var normalizedTenant))
        {
            return false;
        }
        var profiles = account
            .GetTenantProfiles()
            .Where(profile =>
                Guid.TryParse(profile.TenantId, out var profileTenant)
                && profileTenant == normalizedTenant)
            .ToArray();
        if (profiles.Length != 1
            || !Guid.TryParse(profiles[0].Oid, out var objectId))
        {
            return false;
        }
        accountId = $"{normalizedTenant:D}:{objectId:D}";
        return accountId.Length <= MaximumIdentityValueCharacters;
    }

    private sealed record BrokerRequest(
        ushort SchemaVersion,
        string RequestId,
        BrokerOperation Operation,
        string TenantId,
        string ClientId,
        string ApiScope,
        ulong? ParentWindowHandle)
    {
        public bool IsValid()
        {
            return SchemaVersion == Program.SchemaVersion
                && ValidRequestId(RequestId)
                && Guid.TryParseExact(TenantId, "D", out _)
                && Guid.TryParseExact(ClientId, "D", out _)
                && ValidApiScope(ApiScope)
                && (Operation == BrokerOperation.SignInInteractively
                    || ParentWindowHandle is null);
        }

        private static bool ValidRequestId(string value)
        {
            return value.Length is > 0 and <= 128
                && value.All(character =>
                    char.IsAsciiLetterOrDigit(character) || character is '-' or '_');
        }

        private static bool ValidApiScope(string value)
        {
            return value.Length is > 0 and <= MaximumIdentityValueCharacters
                && value.All(character => character <= 0x7f && !char.IsWhiteSpace(character)
                    && !char.IsControl(character))
                && value.EndsWith("/access_as_user", StringComparison.Ordinal)
                && (value.StartsWith("api://", StringComparison.Ordinal)
                    || value.StartsWith("https://", StringComparison.Ordinal));
        }
    }

    private sealed record BrokerResponse(
        ushort SchemaVersion,
        string RequestId,
        BrokerOutcome Outcome,
        string? AccessToken,
        long? ExpiresAtUnixSeconds,
        string? AccountId,
        string? ErrorCode)
    {
        public static BrokerResponse Token(
            BrokerRequest request,
            AuthenticationResult result) =>
            WithToken(request, BrokerOutcome.Token, result);

        public static BrokerResponse SignedIn(
            BrokerRequest request,
            AuthenticationResult result) =>
            WithToken(request, BrokerOutcome.SignedIn, result);

        public static BrokerResponse SignedOut(string requestId) =>
            WithoutToken(requestId, BrokerOutcome.SignedOut);

        public static BrokerResponse SignedInStatus(string requestId, string accountId) =>
            new(
                Program.SchemaVersion,
                requestId,
                BrokerOutcome.SignedInStatus,
                null,
                null,
                accountId,
                null);

        public static BrokerResponse SignedOutStatus(string requestId) =>
            WithoutToken(requestId, BrokerOutcome.SignedOutStatus);

        public static BrokerResponse InteractionRequired(string requestId) =>
            WithoutToken(
                requestId,
                BrokerOutcome.InteractionRequired,
                "INTERACTION_REQUIRED");

        public static BrokerResponse Invalid(string? requestId) =>
            WithoutToken(
                ValidResponseRequestId(requestId) ? requestId! : "invalid-request",
                BrokerOutcome.InvalidRequest,
                "INVALID_REQUEST");

        public static BrokerResponse Unavailable(string? requestId = null) =>
            WithoutToken(
                ValidResponseRequestId(requestId) ? requestId! : "unavailable-request",
                BrokerOutcome.Unavailable,
                "IDENTITY_PROVIDER_UNAVAILABLE");

        private static BrokerResponse WithToken(
            BrokerRequest request,
            BrokerOutcome outcome,
            AuthenticationResult result) =>
            new(
                Program.SchemaVersion,
                request.RequestId,
                outcome,
                result.AccessToken,
                result.ExpiresOn.ToUnixTimeSeconds(),
                RequiredTenantAccountId(result.Account, request.TenantId),
                null);

        private static BrokerResponse WithoutToken(
            string requestId,
            BrokerOutcome outcome,
            string? errorCode = null) =>
            new(Program.SchemaVersion, requestId, outcome, null, null, null, errorCode);

        private static string RequiredTenantAccountId(
            IAccount? account,
            string tenantId)
        {
            return account is not null
                && Program.TryTenantAccountId(account, tenantId, out var accountId)
                ? accountId
                : throw new InvalidOperationException("MSAL did not return an account identity.");
        }

        private static bool ValidResponseRequestId(string? value) =>
            value is { Length: > 0 and <= 128 }
                && value.All(character =>
                    char.IsAsciiLetterOrDigit(character) || character is '-' or '_');
    }

    private enum BrokerOperation
    {
        AcquireTokenSilent,
        SignInInteractively,
        SignOut,
        GetStatus,
    }

    private enum BrokerOutcome
    {
        Token,
        SignedIn,
        SignedOut,
        SignedInStatus,
        SignedOutStatus,
        InteractionRequired,
        Unavailable,
        InvalidRequest,
    }
}
