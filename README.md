# 将豆瓣电影和读书同步到Notion


本项目通过Github Action每天定时同步豆瓣电影和读书到Notion。

### 演员字段容量

电影同步支持将“演员”设为 Notion 的文字或多选字段，并在运行时读取实际类型。
演员姓名很多时，多选选项会让数据库结构超过 Notion 容量限制；文字字段不会为每个新姓名增加选项。
转换已有数据库前，请导出全部演员值，在独立测试库验证多选转文字，并逐条核对转换结果。
文字格式使用逗号连接姓名，长名单分段写入，不截断姓名；原有多选模板仍可使用。

* 豆瓣电影预览效果：https://douban-movie.malinkang.com/
* 豆瓣图书预览效果：https://douban-book.malinkang.com/


## 使用

> [!IMPORTANT]  
> 关注公众号回复豆瓣获取教程，后续有更新也会第一时间在公众号里同步。

![扫码_搜索联合传播样式-标准色版](https://github.com/malinkang/weread2notion/assets/3365208/191900c6-958e-4f9b-908d-a40a54889b5e)


## 群
> [!IMPORTANT]  
> 欢迎加入群讨论。可以讨论使用中遇到的任何问题，也可以讨论Notion使用，后续我也会在群中分享更多Notion自动化工具。微信群失效的话可以添加我的微信malinkang，我拉你入群。

| 微信群 | QQ群 |
| --- | --- |
| <div align="center"><img src="https://github.com/malinkang/Podcast2Notion/assets/3365208/f38804e6-fe05-4754-9188-122a08e43fec" ></div> | <div align="center"><img src="https://images.malinkang.com/2024/04/b225b17d60670e4a6ff3459bbde80d28.jpg" width="50%"></div> |


## 捐赠

如果你觉得本项目帮助了你，请作者喝一杯咖啡，你的支持是作者最大的动力。本项目会持续更新。

| 支付宝支付 | 微信支付 |
| --- | --- |
| <div align="center"><img src="https://images.malinkang.com/2024/03/7fd0feb1145f19fab3821ff1d4631f85.jpg" width="50%"></div> | <div align="center"><img src="https://images.malinkang.com/2024/03/d34f577490a32d4440c8a22f57af41da.jpg" width="50%"></div> |

## 其他项目
* [WeRead2Notion-Pro](https://github.com/malinkang/weread2notion-pro)
* [WeRead2Notion](https://github.com/malinkang/weread2notion)
* [Podcast2Notion](https://github.com/malinkang/podcast2notion)
* [Douban2Notion](https://github.com/malinkang/douban2notion)
* [Keep2Notion](https://github.com/malinkang/keep2notion)
