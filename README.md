# -File-review
对指定文件夹及子文件夹进行查重
![截图](https://github.com/user-attachments/assets/acfbc970-1fb5-4894-9625-cd6e0d6bb687)
目前已完成到1.9版本
1、软件可以对指定目录进行搜索，查找到重复文件后将路径输出到控制台。
2、支持多目录搜索对比，目前仅测试到2个目录，而且当前版本不同磁盘搜索也有点问题，后面修吧。
3、支持筛选关键词，可以填写多个，但是目前还不支持模糊搜索。
4、支持对后缀进行筛选，也不支持模糊搜索。
5、可以对文件名相似度进行要求。
6、开启-d模式以后，筛选到重复文件就会一组一组让用户确定处理方式。
7、指定文件输出路径（未完成）。
8、删除时创建快捷方式，这个功能需要pywin32支持，我让ai写了自动安装的脚本（测试起来麻烦，我就没测试这部分了）。
9、哈希模式，结果文件再进行一次哈希校验，保证准确性，如果哈希校验以后确定不是重复文件就会剔除到删除列表以外。
10、直接删除不确认，必须和-d模式进行配合使用。
