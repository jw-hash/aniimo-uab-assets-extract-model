<h1>伊莫模型提取</h1>

使用 claude sonnet 5.5 编写的.py脚本，需要使用pip 安装Unitypy与numpy库。

uab_extract介绍：适合提取.uab文件里的所有资产，但模型提取只有.obj格式。

uab_to_model: 适合提取.uab模型资产，包括模型骨骼与动画。（v2版本新增针对 Parmon_10XXX01, Parmon_10XXX02等其他编号的伊莫的模型骨骼与动画提取改进）。

示例：python uab_to_model_v4.py ./bundles -c Parmon_10XXX -o ./out --root-motion keep</h1>

描述：（./bundles） 目录是指伊莫游戏里的资产目录， 而 Parmon_10XXX 是指伊莫的模型编号，要找具体的编号可以浏览 （Aniimo_UI_Img_ResearchBook_Enter）。通常 Aniimo_UI_Img_ResearchBook_Enter_10XXX.png 文件名后缀里的编号对应着 Parmon_10XXX 的编号。

具体目录路径 ：Aniimo\game\Aniimo_Data\cvs\res\uab\win\DefaultPackage\CacheBundleFiles\

<h1>Aniimo model extraction</h1>

This .py script was written using Claude Sonnet 5.5，it requires the installation of the UnityPy and NumPy libraries via pip.

uab_extract description: Suitable for extracting all assets from .uab files, but model extraction only supports .obj format.

uab_to_model: Suitable for extracting .uab model assets, including model skeletons and animations. (Version 2 adds improvements for extracting model skeletons and animations for other aniimo models such as Parmon_10XXX01 and Parmon_10XXX02).

Example: python uab_to_model_v4.py ./bundles -c Parmon_10XXX -o ./out --root-motion keep</h1>

Description: The (./bundles) directory refers to the asset directory in the Aniimo game, while Parmon_10XXX refers to Aniimo's model number. To find the specific number, you can browse (Aniimo_UI_Img_ResearchBook_Enter). Usually, the number in the file extension of Aniimo_UI_Img_ResearchBook_Enter_10XXX.png corresponds to the Parmon_10XXX number.

Specific directory path: Aniimo\game\Aniimo_Data\cvs\res\uab\win\DefaultPackage\CacheBundleFiles\
