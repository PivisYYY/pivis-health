import SwiftUI
import PhotosUI

/// 要发进 P-Health 对话的一张照片：来自对话里的相机按钮，或者待办卡上的「拍照」（带待办 id）
struct PendingPhoto {
    let image: UIImage
    var todoId: String? = nil
    var todoTitle: String? = nil
    var fieldId: String? = nil
}

enum PhotoPrep {
    /// 相机原图（1200 万像素）压到长边 1600、JPEG 0.7。放在后台线程做：拍完立刻回到界面，不卡。
    static func jpeg(_ image: UIImage) async -> Data? {
        await Task.detached(priority: .userInitiated) { () -> Data? in
            let s = image.size
            guard s.width > 0, s.height > 0 else { return nil }
            let scale = min(1, 1600 / max(s.width, s.height))
            let size = CGSize(width: (s.width * scale).rounded(), height: (s.height * scale).rounded())
            let fmt = UIGraphicsImageRendererFormat.default()
            fmt.scale = 1
            let out = UIGraphicsImageRenderer(size: size, format: fmt).image { _ in
                image.draw(in: CGRect(origin: .zero, size: size))
            }
            return out.jpegData(compressionQuality: 0.7)
        }.value
    }

    /// 对话里显示用的小图（长边 640），也在后台做
    static func thumbnail(_ image: UIImage) async -> UIImage {
        await Task.detached(priority: .userInitiated) { () -> UIImage in
            let s = image.size
            let scale = min(1, 640 / max(s.width, max(s.height, 1)))
            let size = CGSize(width: (s.width * scale).rounded(), height: (s.height * scale).rounded())
            let fmt = UIGraphicsImageRendererFormat.default()
            fmt.scale = 1
            return UIGraphicsImageRenderer(size: size, format: fmt).image { _ in
                image.draw(in: CGRect(origin: .zero, size: size))
            }
        }.value
    }
}

/// 对话缩略图缓存：刚拍的照片先放进来，上屏不用等网络；历史里的照片按文件名从服务器取
@MainActor
final class ChatPhotoCache: ObservableObject {
    static let shared = ChatPhotoCache()
    @Published private(set) var images: [String: UIImage] = [:]
    private var loading: Set<String> = []

    func put(_ name: String, _ image: UIImage) { images[name] = image }

    func load(_ name: String) {
        guard images[name] == nil, !name.hasPrefix("local-"), !loading.contains(name) else { return }
        loading.insert(name)
        Task {
            // /api/ 下的图：要带设备密钥，走 PivisAPI
            if let (data, _) = try? await PivisAPI.send(PivisAPI.request("api/v3/photo/\(name)")),
               let img = UIImage(data: data) {
                let thumb = await PhotoPrep.thumbnail(img)
                images[name] = thumb
            }
            loading.remove(name)
        }
    }
}

/// 消息里的照片标记：[[photo:文件名]]（服务器把发给 P-Health 的照片路径换成了这个）
enum PhotoMarker {
    static let regex = /\[\[photo:([A-Za-z0-9_.-]+)\]\]/

    static func split(_ text: String) -> (photos: [String], rest: String) {
        let names = text.matches(of: regex).map { String($0.output.1) }
        let rest = text.replacing(regex, with: "").trimmingCharacters(in: .whitespacesAndNewlines)
        return (names, rest)
    }

    static func tag(_ name: String) -> String { "[[photo:\(name)]]" }
}

/// 对话里的一张照片：圆角、细描边，宽 200 以内按比例
struct ChatPhotoView: View {
    let name: String
    var side: CGFloat = 200
    @ObservedObject private var cache = ChatPhotoCache.shared

    var body: some View {
        Group {
            if let img = cache.images[name] {
                let r = img.size.height / max(img.size.width, 1)
                Image(uiImage: img).resizable().scaledToFill()
                    .frame(width: side, height: min(side * 1.33, max(side * 0.6, side * r)))
                    .clipped()
            } else {
                Rectangle().fill(E.surface)
                    .frame(width: side, height: side * 0.75)
                    .overlay(WorkingLine().padding(.horizontal, 40))
                    .onAppear { cache.load(name) }
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).strokeBorder(E.stroke, lineWidth: 1))
        .accessibilityLabel("照片")
    }
}

/// 拍照入口：有相机直接开相机；没有相机（模拟器）开相册。拍完只把 UIImage 交出去，压缩上传在后台做。
struct CaptureSheet: ViewModifier {
    @Binding var isPresented: Bool
    let onImage: (UIImage) -> Void
    @State private var libraryItem: PhotosPickerItem?
    private var cameraAvailable: Bool { UIImagePickerController.isSourceTypeAvailable(.camera) }

    func body(content: Content) -> some View {
        if cameraAvailable {
            content.fullScreenCover(isPresented: $isPresented) {
                CameraPicker { img in
                    isPresented = false
                    if let img { onImage(img) }
                }
                .ignoresSafeArea()
            }
        } else {
            content
                .photosPicker(isPresented: $isPresented, selection: $libraryItem, matching: .images)
                .onChange(of: libraryItem) { _, item in
                    guard let item else { return }
                    libraryItem = nil
                    Task {
                        if let data = try? await item.loadTransferable(type: Data.self), let img = UIImage(data: data) {
                            await MainActor.run { onImage(img) }
                        }
                    }
                }
        }
    }
}

extension View {
    func captureSheet(isPresented: Binding<Bool>, onImage: @escaping (UIImage) -> Void) -> some View {
        modifier(CaptureSheet(isPresented: isPresented, onImage: onImage))
    }
}
