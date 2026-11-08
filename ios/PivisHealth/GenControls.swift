import SwiftUI
import PhotosUI

// MARK: - 生成式输入控件：待办卡和对话里的 question 卡共用同一套
struct GenField: Identifiable, Hashable {
    let id: String
    let type: String            // options / multi / scale / number / text / time
    let label: String
    let options: [(id: String, label: String)]
    let min: Int
    let max: Int
    let minLabel: String?
    let maxLabel: String?
    let unit: String?
    let placeholder: String?
    let allowText: Bool
    var step: Double? = nil

    static func == (a: GenField, b: GenField) -> Bool { a.id == b.id && a.type == b.type && a.label == b.label }
    func hash(into h: inout Hasher) { h.combine(id); h.combine(type); h.combine(label) }

    init(id: String, type: String, label: String, options: [(id: String, label: String)] = [], min: Int = 1, max: Int = 5,
         minLabel: String? = nil, maxLabel: String? = nil, unit: String? = nil, placeholder: String? = nil, allowText: Bool = false,
         step: Double? = nil) {
        self.id = id; self.type = type; self.label = label; self.options = options
        self.min = min; self.max = max; self.minLabel = minLabel; self.maxLabel = maxLabel
        self.unit = unit; self.placeholder = placeholder; self.allowText = allowText; self.step = step
    }

    init(_ i: V3Input) {
        self.init(id: i.id, type: i.type, label: i.label, options: (i.options ?? []).map { ($0.id, $0.label) },
                  min: i.min ?? 1, max: i.max ?? 5, minLabel: i.minLabel, maxLabel: i.maxLabel,
                  unit: i.unit, placeholder: i.placeholder, allowText: i.allowText ?? false, step: i.step)
    }

    func label(forOption id: String) -> String { options.first { $0.id == id }?.label ?? id }
}

enum GenValue: Hashable {
    case choice(String)
    case multi(Set<String>)
    case scale(Int)
    case text(String)
    case photo(Data)      // 待办卡上拍的照片（JPEG），提交时先上传再把服务器路径交给 P-Health

    var isEmpty: Bool {
        switch self {
        case .choice(let s): return s.isEmpty
        case .multi(let s): return s.isEmpty
        case .scale: return false
        case .text(let s): return s.trimmingCharacters(in: .whitespaces).isEmpty
        case .photo(let d): return d.isEmpty
        }
    }

    var json: Any {
        switch self {
        case .choice(let s): return s
        case .multi(let s): return Array(s).sorted()
        case .scale(let n): return n
        case .text(let s): return s
        case .photo: return ""
        }
    }

    func display(_ f: GenField) -> String {
        switch self {
        case .choice(let s): return f.label(forOption: s)
        case .multi(let s): return s.sorted().map { f.label(forOption: $0) }.joined(separator: "、")
        case .scale(let n): return "\(n)"
        case .text(let s): return s + (f.type == "number" ? (f.unit ?? "") : "")
        case .photo: return "照片"
        }
    }
}

struct GenFieldView: View {
    let field: GenField
    @Binding var value: GenValue?
    var onPick: (() -> Void)? = nil      // 单选点下即提交（提议卡）

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if !field.label.isEmpty {
                Text(field.label).font(E.body(13)).foregroundStyle(E.text2)
            }
            switch field.type {
            case "options", "multi":
                FlowLayout(spacing: 6) {
                    ForEach(field.options, id: \.id) { opt in
                        ChoiceChip(label: opt.label, selected: isSelected(opt.id)) { toggle(opt.id) }
                    }
                }
                if field.allowText {
                    LineTextField(placeholder: "自己填", text: textBinding)
                }
            case "scale":
                // 每个分数一个 44×44 的点击格，圆圈照旧画 40（多于 7 个画 30）；一行放不下就换行，不再挤出屏幕
                let small = field.max - field.min > 6
                VStack(alignment: .leading, spacing: 6) {
                    FlowLayout(spacing: small ? 0 : 2) {
                        ForEach(field.min...max(field.min, field.max), id: \.self) { n in
                            let on = value == .scale(n)
                            Button {
                                value = .scale(n)
                                onPick?()
                            } label: {
                                Text("\(n)")
                                    .font(E.body(14))
                                    .foregroundStyle(on ? Color.black : E.text)
                                    .frame(width: small ? 30 : 40, height: small ? 30 : 40)
                                    .background(Circle().fill(on ? E.text : Color.clear))
                                    .overlay(Circle().strokeBorder(on ? E.text : E.stroke, lineWidth: 1))
                                    .frame(width: 44, height: 44)
                                    .contentShape(Rectangle())
                            }
                            .buttonStyle(EPress())
                            .accessibilityLabel("\(n) 分")
                            .accessibilityAddTraits(on ? .isSelected : [])
                        }
                    }
                    .padding(.horizontal, small ? -7 : -2)   // 点击格比圆圈大：往外挪回去，圆圈和标题仍然左对齐
                    if field.minLabel != nil || field.maxLabel != nil {
                        HStack {
                            Text(field.minLabel ?? "")
                            Spacer()
                            Text(field.maxLabel ?? "")
                        }
                        .font(E.body(11)).foregroundStyle(E.text3)
                    }
                }
            case "number" where field.step != nil:
                // 有步长：− 数 + （体重 0.1、次数 1），先填上次的值，点一下改一点
                HStack(alignment: .center, spacing: 14) {
                    StepButton(symbol: "minus") { bump(-1) }
                    Text(numberText.isEmpty ? "—" : numberText)
                        .font(E.light(34)).foregroundStyle(E.text).monospacedDigit()
                        .frame(minWidth: 70)
                    if let u = field.unit, !u.isEmpty { Text(u).font(E.body(15)).foregroundStyle(E.text2) }
                    StepButton(symbol: "plus") { bump(1) }
                }
            case "number":
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    TextField(field.placeholder ?? "填数字", text: textBinding)
                        .keyboardType(.decimalPad)
                        .font(E.light(28))
                        .foregroundStyle(E.text)
                        .frame(maxWidth: 140)
                    if let u = field.unit { Text(u).font(E.body(15)).foregroundStyle(E.text2) }
                }
                .overlay(alignment: .bottom) { Hairline().allowsHitTesting(false) }
            case "photo":
                PhotoField(value: $value)
            default:
                LineTextField(placeholder: field.placeholder ?? (field.type == "time" ? "比如 13:00" : "写一句"), text: textBinding)
            }
        }
    }

    private var numberText: String {
        if case .text(let s) = value { return s }
        return ""
    }

    private func bump(_ dir: Double) {
        let step = field.step ?? 1
        let cur = Double(numberText) ?? 0
        let next = max(0, cur + dir * step)
        let digits = step < 1 ? max(1, Int((-log10(step)).rounded(.up))) : 0
        value = .text(digits == 0 ? String(Int(next.rounded())) : String(format: "%.\(digits)f", next))
    }

    private func isSelected(_ id: String) -> Bool {
        switch value {
        case .choice(let s): return s == id
        case .multi(let s): return s.contains(id)
        default: return false
        }
    }

    private func toggle(_ id: String) {
        if field.type == "multi" {
            var set: Set<String> = []
            if case .multi(let s) = value { set = s }
            if set.contains(id) { set.remove(id) } else { set.insert(id) }
            value = .multi(set)
        } else {
            value = .choice(id)
            onPick?()
        }
    }

    private var textBinding: Binding<String> {
        Binding(get: {
            if case .text(let s) = value { return s }
            return ""
        }, set: { raw in
            guard field.type == "number" else { value = .text(raw); return }
            // 数字框：全角句号/逗号统一成小数点，只留数字和一个小数点
            var out = "", dot = false
            for ch in raw.replacingOccurrences(of: "。", with: ".").replacingOccurrences(of: "，", with: ".")
                .replacingOccurrences(of: ",", with: ".").replacingOccurrences(of: "．", with: ".") {
                if ch.isASCII && ch.isNumber { out.append(ch) }
                else if ch == "." && !dot { out.append(ch); dot = true }
            }
            value = .text(out)
        })
    }
}

/// 下划线输入框
struct LineTextField: View {
    let placeholder: String
    @Binding var text: String
    var onSubmit: (() -> Void)? = nil
    var body: some View {
        TextField("", text: $text, prompt: Text(placeholder).foregroundStyle(E.hint))
            .font(E.body(13))
            .foregroundStyle(E.text)
            .submitLabel(.send)
            .onSubmit { onSubmit?() }
            .frame(minHeight: 40)
            .overlay(alignment: .bottom) { Hairline().allowsHitTesting(false) }
    }
}

/// 简单换行布局（选项胶囊）
struct FlowLayout: Layout {
    var spacing: CGFloat = 6
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxW = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, rowH: CGFloat = 0, widest: CGFloat = 0
        for s in subviews {
            let sz = s.sizeThatFits(.unspecified)
            if x > 0 && x + sz.width > maxW { x = 0; y += rowH + spacing; rowH = 0 }
            x += sz.width + spacing
            rowH = max(rowH, sz.height)
            widest = max(widest, x)
        }
        return CGSize(width: min(widest, maxW), height: y + rowH)
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, rowH: CGFloat = 0
        for s in subviews {
            let sz = s.sizeThatFits(.unspecified)
            if x > bounds.minX && x + sz.width > bounds.maxX { x = bounds.minX; y += rowH + spacing; rowH = 0 }
            s.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(sz))
            x += sz.width + spacing
            rowH = max(rowH, sz.height)
        }
    }
}

// MARK: - 拍照输入：有相机就拍，没有（模拟器）就从相册选；选好显示缩略图，可重拍
struct PhotoField: View {
    @Binding var value: GenValue?
    @State private var pickerItem: PhotosPickerItem?
    @State private var showCamera = false
    @State private var thumb: UIImage?
    @State private var preparing = false
    private var cameraAvailable: Bool { UIImagePickerController.isSourceTypeAvailable(.camera) }

    /// 压缩放后台：拍完立刻回到表单，缩略图先上，JPEG 好了再填进值里
    private func accept(_ img: UIImage) {
        preparing = true
        Task {
            let t = await PhotoPrep.thumbnail(img)
            await MainActor.run { thumb = t }
            let d = await PhotoPrep.jpeg(img)
            await MainActor.run {
                preparing = false
                if let d { value = .photo(d) }
            }
        }
    }

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            if let img = thumb, value != nil || preparing {
                Image(uiImage: img).resizable().scaledToFill()
                    .frame(width: 64, height: 64)
                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(E.stroke, lineWidth: 1))
                    .accessibilityLabel("已选的照片")
            }
            if cameraAvailable {
                ChoiceChip(label: value == nil ? "拍照" : "重拍", selected: false) { showCamera = true }
            }
            PhotosPicker(selection: $pickerItem, matching: .images) {
                Text(cameraAvailable ? "相册" : (value == nil ? "选照片" : "换一张"))
                    .font(E.body(14)).foregroundStyle(E.text)
                    .padding(.horizontal, 14).frame(height: 36)
                    .overlay(Capsule().strokeBorder(E.stroke, lineWidth: 1))
            }
            .accessibilityIdentifier("photo-pick")
        }
        .onChange(of: pickerItem) { _, item in
            guard let item else { return }
            Task {
                if let data = try? await item.loadTransferable(type: Data.self), let img = UIImage(data: data) {
                    await MainActor.run { accept(img) }
                }
            }
        }
        .fullScreenCover(isPresented: $showCamera) {
            CameraPicker { img in
                showCamera = false
                if let img { accept(img) }
            }
            .ignoresSafeArea()
        }
    }
}

struct CameraPicker: UIViewControllerRepresentable {
    let onDone: (UIImage?) -> Void
    func makeCoordinator() -> Coordinator { Coordinator(onDone: onDone) }
    func makeUIViewController(context: Context) -> UIImagePickerController {
        let c = UIImagePickerController()
        c.sourceType = .camera
        c.delegate = context.coordinator
        return c
    }
    func updateUIViewController(_ c: UIImagePickerController, context: Context) {}
    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let onDone: (UIImage?) -> Void
        init(onDone: @escaping (UIImage?) -> Void) { self.onDone = onDone }
        func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            onDone(info[.originalImage] as? UIImage)
        }
        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) { onDone(nil) }
    }
}


/// 数值卡的 − / + 圆按钮
struct StepButton: View {
    let symbol: String
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Image(systemName: symbol).font(.system(size: 13, weight: .light))
                .foregroundStyle(E.text2)
                .frame(width: 40, height: 40)
                .overlay(Circle().strokeBorder(E.stroke, lineWidth: 1))
        }
        .buttonStyle(EPress())
        .accessibilityLabel(symbol == "plus" ? "加" : "减")
    }
}
