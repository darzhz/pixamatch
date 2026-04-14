import torch
import torch.nn as nn

class Conv_block(nn.Module):
    def __init__(self, in_c, out_c, kernel=(1, 1), stride=(1, 1), padding=(0, 0), groups=1):
        super(Conv_block, self).__init__()
        self.conv = nn.Conv2d(in_c, out_channels=out_c, kernel_size=kernel, groups=groups, stride=stride, padding=padding, bias=False)
        self.bn = nn.BatchNorm2d(out_c)
        self.prelu = nn.PReLU(out_c)
    def forward(self, x):
        x = self.conv(x)
        x = self.bn(x)
        x = self.prelu(x)
        return x

class Linear_block(nn.Module):
    def __init__(self, in_c, out_c, kernel=(1, 1), stride=(1, 1), padding=(0, 0), groups=1):
        super(Linear_block, self).__init__()
        self.conv = nn.Conv2d(in_c, out_channels=out_c, kernel_size=kernel, groups=groups, stride=stride, padding=padding, bias=False)
        self.bn = nn.BatchNorm2d(out_c)
    def forward(self, x):
        x = self.conv(x)
        x = self.bn(x)
        return x

class Depthwise_block(nn.Module):
    def __init__(self, in_c, out_c, kernel=(3, 3), stride=(2, 2), padding=(1, 1), groups=1):
        super(Depthwise_block, self).__init__()
        self.conv = Conv_block(in_c, out_c=groups, kernel=(1, 1), padding=(0, 0), stride=(1, 1))
        self.dw_conv = Conv_block(groups, out_c=groups, kernel=kernel, padding=padding, stride=stride, groups=groups)
        self.pw_conv = Linear_block(groups, out_c=out_c, kernel=(1, 1), padding=(0, 0), stride=(1, 1))
    def forward(self, x):
        x = self.conv(x)
        x = self.dw_conv(x)
        x = self.pw_conv(x)
        return x

class Residual_block(nn.Module):
    def __init__(self, in_c, out_c, kernel=(3, 3), stride=(1, 1), padding=(1, 1), groups=1):
        super(Residual_block, self).__init__()
        self.dw_block = Depthwise_block(in_c, out_c, kernel, stride, padding, groups)
    def forward(self, x):
        return x + self.dw_block(x)

class MobileFaceNet(nn.Module):
    def __init__(self, embedding_size=128):
        super(MobileFaceNet, self).__init__()
        self.conv1 = Conv_block(3, 64, kernel=(3, 3), stride=(2, 2), padding=(1, 1))
        self.dw_convexp = Conv_block(64, 64, kernel=(3, 3), stride=(1, 1), padding=(1, 1), groups=64)
        self.blocks = nn.Sequential(
            Depthwise_block(64, 64, kernel=(3, 3), stride=(2, 2), padding=(1, 1), groups=128),
            Residual_block(64, 64, kernel=(3, 3), stride=(1, 1), padding=(1, 1), groups=128),
            Residual_block(64, 64, kernel=(3, 3), stride=(1, 1), padding=(1, 1), groups=128),
            Residual_block(64, 64, kernel=(3, 3), stride=(1, 1), padding=(1, 1), groups=128),
            Residual_block(64, 64, kernel=(3, 3), stride=(1, 1), padding=(1, 1), groups=128),
            Depthwise_block(64, 128, kernel=(3, 3), stride=(2, 2), padding=(1, 1), groups=256),
            Residual_block(128, 128, kernel=(3, 3), stride=(1, 1), padding=(1, 1), groups=256),
            Residual_block(128, 128, kernel=(3, 3), stride=(1, 1), padding=(1, 1), groups=256),
            Residual_block(128, 128, kernel=(3, 3), stride=(1, 1), padding=(1, 1), groups=256),
            Residual_block(128, 128, kernel=(3, 3), stride=(1, 1), padding=(1, 1), groups=256),
            Residual_block(128, 128, kernel=(3, 3), stride=(1, 1), padding=(1, 1), groups=256),
            Residual_block(128, 128, kernel=(3, 3), stride=(1, 1), padding=(1, 1), groups=256),
            Depthwise_block(128, 128, kernel=(3, 3), stride=(2, 2), padding=(1, 1), groups=512),
            Residual_block(128, 128, kernel=(3, 3), stride=(1, 1), padding=(1, 1), groups=256),
            Residual_block(128, 128, kernel=(3, 3), stride=(1, 1), padding=(1, 1), groups=256),
        )
        self.conv2 = Conv_block(128, 512, kernel=(1, 1), stride=(1, 1), padding=(0, 0))
        self.linear7 = Linear_block(512, 512, groups=512, kernel=(7, 7), stride=(1, 1), padding=(0, 0))
        self.linear1 = Linear_block(512, embedding_size, kernel=(1, 1), stride=(1, 1), padding=(0, 0))
    
    def forward(self, x):
        x = self.conv1(x)
        x = self.dw_convexp(x)
        x = self.blocks(x)
        x = self.conv2(x)
        x = self.linear7(x)
        x = self.linear1(x)
        x = x.view(x.size(0), -1)
        return x

if __name__ == '__main__':
    model = MobileFaceNet()
    model.load_state_dict(torch.load('models/mobilefacenet.pt', map_location='cpu'))
    model.eval()
    
    dummy_input = torch.randn(1, 3, 112, 112)
    torch.onnx.export(model, dummy_input, "models/mobilefacenet.onnx", 
                      input_names=['input'], output_names=['output'], 
                      opset_version=11)
    print("Exported to models/mobilefacenet.onnx")
