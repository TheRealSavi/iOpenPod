// A small typed C boundary keeps Sparkle's Objective-C blocks out of ctypes.
#import <Cocoa/Cocoa.h>
#import <Sparkle/Sparkle.h>

typedef void (*IOPUpdateEvent)(int event, double progress, const char *detail);

@interface IOPUpdateDriver : NSObject <SPUUserDriver, SPUUpdaterDelegate>
@property(nonatomic, strong) SPUUpdater *updater;
@property(nonatomic, copy) NSString *version;
@property(nonatomic, copy) NSString *url;
@property(nonatomic) uint64_t size;
@property(nonatomic) uint64_t received;
@property(nonatomic) IOPUpdateEvent callback;
@property(nonatomic) BOOL authorized;
@property(nonatomic) BOOL handedOff;
@property(nonatomic) BOOL terminal;
@property(nonatomic, copy) void (^cancel)(void);
@property(nonatomic, copy) void (^resume)(void);
@end

@implementation IOPUpdateDriver
- (void)fail:(NSString *)message {
    if (!self.terminal) {
        self.terminal = YES;
        self.authorized = NO;
        self.callback(2, 0, message.UTF8String);
    }
}
- (void)showUpdatePermissionRequest:(SPUUpdatePermissionRequest *)request reply:(void (^)(SUUpdatePermissionResponse *))reply {
    reply([[SUUpdatePermissionResponse alloc] initWithAutomaticUpdateChecks:NO automaticUpdateDownloading:@NO sendSystemProfile:NO]);
}
- (void)showUserInitiatedUpdateCheckWithCancellation:(void (^)(void))cancellation {
    self.cancel = cancellation;
}
- (void)showUpdateFoundWithAppcastItem:(SUAppcastItem *)item state:(SPUUserUpdateState *)state reply:(void (^)(SPUUserUpdateChoice))reply {
    self.cancel = nil;
    if (!self.authorized || item.informationOnlyUpdate ||
        ![item.versionString isEqualToString:self.version] ||
        ![item.fileURL.absoluteString isEqualToString:self.url] ||
        item.contentLength != self.size || ![item.installationType isEqualToString:@"application"] ||
        item.signingValidationStatus != SPUAppcastSigningValidationStatusSucceeded) {
        reply(state.stage == SPUUpdateStateInstalling ? SPUUserUpdateChoiceSkip : SPUUserUpdateChoiceDismiss);
        [self fail:@"The signed Sparkle feed does not match the selected release"];
        return;
    }
    reply(SPUUserUpdateChoiceInstall);
}
- (void)showUpdateReleaseNotesWithDownloadData:(SPUDownloadData *)data {}
- (void)showUpdateReleaseNotesFailedToDownloadWithError:(NSError *)error {}
- (void)showUpdateNotFoundWithError:(NSError *)error acknowledgement:(void (^)(void))acknowledgement {
    [self fail:error.localizedDescription];
    acknowledgement();
}
- (void)showUpdaterError:(NSError *)error acknowledgement:(void (^)(void))acknowledgement {
    [self fail:error.localizedDescription];
    acknowledgement();
}
- (void)showDownloadInitiatedWithCancellation:(void (^)(void))cancellation {
    self.cancel = cancellation;
    self.received = 0;
}
- (void)showDownloadDidReceiveExpectedContentLength:(uint64_t)length {}
- (void)showDownloadDidReceiveDataOfLength:(uint64_t)length {
    self.received += length;
    self.callback(0, self.size ? MIN(1.0, (double)self.received / self.size) : 0, "Downloading update");
}
- (void)showDownloadDidStartExtractingUpdate {
    self.cancel = nil;
    self.callback(0, 1, "Verifying update");
}
- (void)showExtractionReceivedProgress:(double)progress {
    self.callback(0, progress, "Preparing update");
}
- (void)showReadyToInstallAndRelaunch:(void (^)(SPUUserUpdateChoice))reply {
    reply(self.authorized ? SPUUserUpdateChoiceInstall : SPUUserUpdateChoiceSkip);
}
- (void)showInstallingUpdateWithApplicationTerminated:(BOOL)terminated retryTerminatingApplication:(void (^)(void))retry {}
- (void)showUpdateInstalledAndRelaunched:(BOOL)relaunched acknowledgement:(void (^)(void))acknowledgement {
    acknowledgement();
}
- (void)dismissUpdateInstallation {
    self.cancel = nil;
}
- (BOOL)updater:(SPUUpdater *)updater shouldPostponeRelaunchForUpdate:(SUAppcastItem *)item untilInvokingBlock:(void (^)(void))handler {
    self.resume = handler;
    self.callback(1, 1, "Ready to restart");
    return YES;
}
- (BOOL)updaterShouldRelaunchApplication:(SPUUpdater *)updater {
    // Sparkle calls this before the postponement hook as well as after resuming.
    return self.authorized;
}
- (void)updater:(SPUUpdater *)updater didAbortWithError:(NSError *)error {
    [self fail:error.localizedDescription];
}
@end

// Sparkle delegates are weak; this owner survives until termination/cancellation.
static IOPUpdateDriver *driver;

int iop_update_start(const char *version, const char *url, uint64_t size, IOPUpdateEvent callback) {
    NSCAssert([NSThread isMainThread], @"Sparkle must run on the Qt main thread");
    if (driver && driver.updater.sessionInProgress) return 0;
    driver = [IOPUpdateDriver new];
    driver.version = [NSString stringWithUTF8String:version];
    driver.url = [NSString stringWithUTF8String:url];
    driver.size = size;
    driver.callback = callback;
    driver.authorized = YES;
    NSBundle *host = NSBundle.mainBundle;
    driver.updater = [[SPUUpdater alloc] initWithHostBundle:host applicationBundle:host userDriver:driver delegate:driver];
    NSError *error = nil;
    if (![driver.updater startUpdater:&error]) {
        [driver fail:error.localizedDescription];
        return 0;
    }
    driver.updater.automaticallyChecksForUpdates = NO;
    driver.updater.automaticallyDownloadsUpdates = NO;
    [driver.updater checkForUpdates];
    return 1;
}

void iop_update_resume(void) {
    NSCAssert([NSThread isMainThread], @"Sparkle must run on the Qt main thread");
    if (driver.authorized && driver.resume) {
        driver.handedOff = YES;
        void (^resume)(void) = driver.resume;
        driver.resume = nil;
        resume();
    }
}

void iop_update_cancel(void) {
    if (!driver.handedOff) {
        driver.authorized = NO;
        if (driver.cancel) {
            void (^cancel)(void) = driver.cancel;
            driver.cancel = nil;
            cancel();
        }
    }
}
