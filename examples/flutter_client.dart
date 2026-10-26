// import 'dart:typed_data';
// import 'package:dio/dio.dart';

// enum CardType { ktp, businessCard, auto }

// class CardOcrClient {
//   final Dio _dio;

//   CardOcrClient(String baseUrl, {Map<String, String> headers = const {}})
//       : _dio = Dio(BaseOptions(
//           baseUrl: baseUrl.replaceFirst(RegExp(r'/$'), ''),
//           connectTimeout: const Duration(seconds: 10),
//           sendTimeout: const Duration(seconds: 20),
//           receiveTimeout: const Duration(seconds: 90),
//           headers: headers,
//         ));

//   /// Works on Flutter web, Android and iOS. Supply XFile.readAsBytes(), for example.
//   Future<Map<String, dynamic>> scan(
//     Uint8List image, {
//     CardType type = CardType.auto,
//     bool accurate = true,
//     String? phoneRegion,
//     CancelToken? cancelToken,
//   }) async {
//     if (image.isEmpty || image.length > 10 * 1024 * 1024) {
//       throw ArgumentError('Choose an image between 1 byte and 10 MB.');
//     }
//     final documentType = switch (type) {
//       CardType.ktp => 'ktp',
//       CardType.businessCard => 'business_card',
//       CardType.auto => 'auto',
//     };
//     final response = await _dio.post<Map<String, dynamic>>(
//       '/v1/ocr/$documentType',
//       data: FormData.fromMap({
//         'file': MultipartFile.fromBytes(image, filename: 'card-upload.jpg'),
//         'mode': accurate ? 'accurate' : 'fast',
//         'include_raw': 'false',
//         if (phoneRegion != null) 'phone_region': phoneRegion,
//       }),
//       cancelToken: cancelToken,
//     );
//     return response.data!;
//   }

//   void close() => _dio.close();
// }

// // Add dio to pubspec.yaml: flutter pub add dio
// // final client = CardOcrClient('https://your-app-api.example.com');
// // final result = await client.scan(await pickedImage.readAsBytes(), type: CardType.ktp);
// // final nik = (result['data'] as Map<String, dynamic>)['nik'] as String?;
// // if (result['needs_review'] == true) showReviewForm(result['fields']);
// // Catch DioException: e.response?.data['error'] contains code and message.
// // X-API-Key is for direct local testing/server-to-server use; keep production secrets on your backend.
