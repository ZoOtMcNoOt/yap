fn main() {
    println!("cargo:rerun-if-env-changed=YAP_BUILD_GIT_SHA");
    let build_git_sha =
        std::env::var("YAP_BUILD_GIT_SHA").unwrap_or_else(|_| "unbound".to_string());
    if build_git_sha != "unbound"
        && (build_git_sha.len() != 40
            || !build_git_sha
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)))
    {
        panic!("YAP_BUILD_GIT_SHA must be one lowercase 40-character Git SHA");
    }
    println!("cargo:rustc-env=YAP_BUILD_GIT_SHA={build_git_sha}");
    println!("cargo:rerun-if-changed=icons/icon.ico");
    println!("cargo:rerun-if-changed=icons/32x32.png");
    println!("cargo:rerun-if-changed=icons/128x128.png");
    println!("cargo:rerun-if-changed=icons/128x128@2x.png");
    println!("cargo:rerun-if-changed=icons/icon.png");
    tauri_build::build()
}
